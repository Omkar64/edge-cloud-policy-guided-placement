"""Run a live, policy-only Phase 2 decision against an explicitly selected cluster."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cloud.config import CloudConfig
from cloud.providers.kubectl_provider import KubectlKubernetesProvider, KubectlPodPingProbe
from cloud.providers.kubernetes_node_provider import KubernetesNodeProvider
from cloud.types import BackgroundScenario, NodeLoadTarget
from orchestration.policy_guided_placement import OPAClient, policy_guided_placement


def _find_type(nodes, node_type: str):
    matches = [node for node in nodes if node.labels.get("pac.io/node-type") == node_type]
    if not matches:
        raise ValueError(f"No ready Kubernetes node has pac.io/node-type={node_type!r}")
    return sorted(matches, key=lambda node: node.name)[0]


def run_live_decision(
    *,
    kubeconfig: str | Path,
    config_path: str | Path,
    workload_path: str | Path,
    output_path: str | Path,
    cpu_node_type: str = "edge",
    memory_node_type: str = "cloud",
    idle_node_type: str | None = None,
    cpu_stress_percent: float = 80,
    memory_stress_percent: float = 90,
    duration_seconds: int = 300,
    stabilization_seconds: int = 40,
    latency_target: str = "1.1.1.1",
    place_demo: bool = False,
    placement_timeout_seconds: float = 120,
) -> dict:
    """Create temporary probe/stress Pods, evaluate via OPA, persist, and clean up.

    By default this function only recommends a node. With place_demo=True it
    creates a temporary, bounded Job only after OPA filtering and weighted
    scoring have selected the final node.
    """
    if duration_seconds <= 0 or stabilization_seconds < 0:
        raise ValueError("duration_seconds must be positive and stabilization_seconds non-negative")
    config = CloudConfig.from_toml(config_path)
    with Path(workload_path).open(encoding="utf-8") as source_file:
        workload = json.load(source_file)
    if not isinstance(workload, dict):
        raise ValueError("Workload JSON must contain an object")
    required_workload_fields = {
        "cpu_required", "memory_required", "max_latency", "max_cpu_utilization",
        "max_memory_utilization", "max_cost", "required_security",
    }
    missing_fields = required_workload_fields - workload.keys()
    if missing_fields:
        raise ValueError(f"Workload JSON is missing required fields: {', '.join(sorted(missing_fields))}")

    provider = KubectlKubernetesProvider(kubeconfig=str(kubeconfig))
    nodes = provider.list_nodes()
    cpu_node = _find_type(nodes, cpu_node_type)
    memory_node = _find_type(nodes, memory_node_type)
    if cpu_node.name == memory_node.name:
        raise ValueError("CPU and memory stress targets must be different nodes")
    targets = {
        cpu_node.name: NodeLoadTarget(cpu_utilization_percent=cpu_stress_percent),
        memory_node.name: NodeLoadTarget(memory_utilization_percent=memory_stress_percent),
    }
    idle_node = None
    if idle_node_type:
        idle_node = _find_type(nodes, idle_node_type)
        if idle_node.name in targets:
            raise ValueError("Idle node must be different from CPU and memory stress targets")
        targets[idle_node.name] = NodeLoadTarget()
    scenario = BackgroundScenario("live-cpu-memory-heterogeneity", targets, duration_seconds)

    probe_pods: dict[str, str] = {}
    stress_handle = None
    placement_handle = None
    demo_placement = None
    placement_verified = False
    try:
        probe_pods = provider.apply_latency_probe_pods(nodes, duration_seconds + stabilization_seconds + 180)
        for pod_name in probe_pods.values():
            provider._run("wait", "--for=condition=Ready", "pod/" + pod_name, "--timeout=120s")
        stress_handle = provider.apply_background_scenario(scenario)
        for pod_name in stress_handle.pod_names:
            provider._run("wait", "--for=condition=Ready", "pod/" + pod_name, "--timeout=120s")
        time.sleep(stabilization_seconds)

        provider.latency_probe = KubectlPodPingProbe(
            provider, probe_pods, target=latency_target, sample_count=3
        )
        adapted_nodes = KubernetesNodeProvider(provider, config).get_nodes()
        # This call performs OPA filtering and then the existing weighted
        # scoring. Placement receives only its final selected_node result.
        decision = policy_guided_placement(adapted_nodes, workload, OPAClient(config.opa_url))
        if place_demo:
            selected = decision["selected_node"]
            if selected is None:
                demo_placement = {
                    "job_name": None,
                    "selected_node": None,
                    "observed_node": None,
                    "scheduling_status": "skipped_no_candidate",
                    "reason": "OPA and scoring produced no eligible selected node",
                }
            else:
                selected_kubernetes_node = next(
                    (node for node in nodes if node.name == selected["id"]), None
                )
                if selected_kubernetes_node is None:
                    demo_placement = {
                        "job_name": None,
                        "selected_node": selected["id"],
                        "observed_node": None,
                        "scheduling_status": "failed",
                        "reason": "Selected node was not present in the Kubernetes inventory",
                    }
                else:
                    try:
                        placement_handle = provider.create_demo_job(
                            selected_kubernetes_node, workload, duration_seconds=240, ttl_seconds=60
                        )
                        observed = provider.wait_for_demo_job(
                            placement_handle, timeout_seconds=placement_timeout_seconds
                        )
                        placement_verified = (
                            observed.status == "scheduled"
                            and observed.observed_node == selected_kubernetes_node.name
                        )
                        demo_placement = {
                            "job_name": placement_handle.job_name,
                            "selected_node": selected_kubernetes_node.name,
                            "observed_node": observed.observed_node,
                            "scheduling_status": "scheduled" if placement_verified else observed.status,
                            "reason": observed.reason,
                        }
                    except Exception as exc:
                        demo_placement = {
                            "job_name": placement_handle.job_name if placement_handle else None,
                            "selected_node": selected_kubernetes_node.name,
                            "observed_node": None,
                            "scheduling_status": "failed",
                            "reason": str(exc),
                        }
        result = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "cluster_region": config.region,
            "scenario": {
                "name": scenario.name,
                "duration_seconds": duration_seconds,
                "cpu_node": cpu_node.name,
                "cpu_target_percent": cpu_stress_percent,
                "memory_node": memory_node.name,
                "memory_target_percent": memory_stress_percent,
                "idle_node": idle_node.name if idle_node else None,
                "latency_probe_target": latency_target,
            },
            "workload": workload,
            "observed_nodes": adapted_nodes,
            "decision": decision,
            "demo_placement": demo_placement,
        }
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as destination:
            destination.write(json.dumps(result, sort_keys=True) + "\n")
        return result
    finally:
        try:
            try:
                if placement_handle is not None and not placement_verified:
                    provider.delete_demo_job(placement_handle)
            finally:
                if stress_handle is not None:
                    provider.clear_background_scenario(stress_handle)
        finally:
            if probe_pods:
                provider.clear_latency_probe_pods(list(probe_pods.values()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True, help="Explicit kubeconfig for the target cluster")
    parser.add_argument("--config", type=Path, required=True, help="Cloud TOML with region, labels, and instance costs")
    parser.add_argument("--workload", type=Path, required=True, help="JSON file with the Phase 1 workload schema")
    parser.add_argument("--output", type=Path, default=ROOT / "results/raw/live_cloud_decisions.jsonl")
    parser.add_argument("--cpu-node-type", default="edge")
    parser.add_argument("--memory-node-type", default="cloud")
    parser.add_argument("--idle-node-type", default=None)
    parser.add_argument("--cpu-stress-percent", type=float, default=80)
    parser.add_argument("--memory-stress-percent", type=float, default=90)
    parser.add_argument("--duration", type=int, default=300, help="Seconds of load after target allocation")
    parser.add_argument("--stabilization", type=int, default=40, help="Seconds to wait before sampling")
    parser.add_argument("--latency-target", default="1.1.1.1", help="ICMP target probed from each worker")
    parser.add_argument(
        "--place-demo", action="store_true",
        help="After OPA filtering and weighted scoring, create and verify a temporary demo Job",
    )
    parser.add_argument("--placement-timeout", type=float, default=120,
                        help="Seconds to wait for the Job Pod to be assigned to the selected node")
    args = parser.parse_args()
    result = run_live_decision(
        kubeconfig=args.kubeconfig,
        config_path=args.config,
        workload_path=args.workload,
        output_path=args.output,
        cpu_node_type=args.cpu_node_type,
        memory_node_type=args.memory_node_type,
        idle_node_type=args.idle_node_type,
        cpu_stress_percent=args.cpu_stress_percent,
        memory_stress_percent=args.memory_stress_percent,
        duration_seconds=args.duration,
        stabilization_seconds=args.stabilization,
        latency_target=args.latency_target,
        place_demo=args.place_demo,
        placement_timeout_seconds=args.placement_timeout,
    )
    selected = result["decision"]["selected_node"]
    print(json.dumps({
        "selected_node": selected["id"] if selected else None,
        "rejected": result["decision"]["rejected"],
        "demo_placement": result["demo_placement"],
        "output": str(args.output),
    }, indent=2))
    if args.place_demo and result["demo_placement"]["scheduling_status"] not in {
        "scheduled", "skipped_no_candidate",
    }:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
