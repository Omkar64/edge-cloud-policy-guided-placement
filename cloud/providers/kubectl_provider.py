"""Live Kubernetes provider implemented through the installed kubectl CLI.

This avoids a Python Kubernetes SDK dependency. Metrics Server supplies CPU and
memory usage; latency must come from an explicitly injected probe.
"""
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
import re
import subprocess
import time
import uuid

from cloud.background_stress import build_background_stress_pods
from cloud.node_adapter import MetricsUnavailableError
from cloud.types import (BackgroundLoadHandle, BackgroundScenario, DemoJobHandle,
                         DemoJobStatus, KubernetesNode, NodeMetrics)


class KubectlKubernetesProvider:
    """KubernetesProvider backed by kubectl and Metrics Server."""

    def __init__(
        self,
        kubeconfig: str | None = None,
        kubectl: str = "kubectl",
        latency_probe: Callable[[str], float] | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        poll_interval_seconds: float = 2,
    ) -> None:
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be non-negative")
        self.kubeconfig = kubeconfig
        self.kubectl = kubectl
        self.latency_probe = latency_probe
        self.command_runner = command_runner
        self.poll_interval_seconds = poll_interval_seconds

    def _run(self, *args: str, input_text: str | None = None) -> str:
        command = [self.kubectl]
        if self.kubeconfig:
            command.extend(["--kubeconfig", self.kubeconfig])
        command.extend(args)
        try:
            result = self.command_runner(
                command, input=input_text, text=True, capture_output=True, check=True
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", None) or str(exc)
            raise RuntimeError(f"kubectl command failed: {detail}") from exc
        return result.stdout

    def list_nodes(self) -> list[KubernetesNode]:
        response = json.loads(self._run("get", "nodes", "-o", "json"))
        return [KubernetesNode.from_api_object(item) for item in response.get("items", [])]

    def get_node_metrics(self, node_names: Sequence[str] | None = None) -> Mapping[str, NodeMetrics]:
        if self.latency_probe is None:
            raise MetricsUnavailableError(
                "Live CPU/memory metrics are available, but a measured node latency probe is required"
            )
        response = json.loads(self._run(
            "get", "--raw", "/apis/metrics.k8s.io/v1beta1/nodes"
        ))
        requested = set(node_names) if node_names is not None else None
        metrics: dict[str, NodeMetrics] = {}
        for item in response.get("items", []):
            name = item.get("metadata", {}).get("name")
            usage = item.get("usage", {})
            if not name or (requested is not None and name not in requested):
                continue
            timestamp = item.get("timestamp")
            if not timestamp:
                raise MetricsUnavailableError(f"Metrics Server omitted timestamp for node {name!r}")
            try:
                latency = float(self.latency_probe(name))
            except (TypeError, ValueError, OSError, RuntimeError) as exc:
                raise MetricsUnavailableError(f"Latency probe failed for node {name!r}: {exc}") from exc
            if latency < 0 or latency != latency or latency == float("inf"):
                raise MetricsUnavailableError(f"Latency probe returned an invalid value for node {name!r}")
            if "cpu" not in usage or "memory" not in usage:
                raise MetricsUnavailableError(f"Metrics Server omitted CPU or memory usage for node {name!r}")
            metrics[name] = NodeMetrics(
                cpu_usage=usage["cpu"],
                memory_usage=usage["memory"],
                latency_ms=latency,
                sampled_at=timestamp,
                latency_source=getattr(self.latency_probe, "source", "injected_node_probe"),
            )
        missing = requested - metrics.keys() if requested is not None else set()
        if missing:
            raise MetricsUnavailableError(
                f"Metrics unavailable for Kubernetes node(s): {', '.join(sorted(missing))}"
            )
        return metrics

    def apply_background_scenario(self, scenario: BackgroundScenario) -> BackgroundLoadHandle:
        manifests = build_background_stress_pods(self.list_nodes(), scenario)
        if not manifests:
            return BackgroundLoadHandle(scenario_name=scenario.name)
        self._run(
            # These manifests are generated locally with known shapes. Skip
            # kubectl's OpenAPI discovery validation, which can time out on
            # restricted or intermittently reachable EKS endpoints; the API
            # server still validates submitted objects.
            "apply", "--validate=false", "-f", "-",
            input_text=json.dumps({"apiVersion": "v1", "kind": "List", "items": manifests}),
        )
        return BackgroundLoadHandle(
            scenario_name=scenario.name,
            pod_names=tuple(pod["metadata"]["name"] for pod in manifests),
        )

    def apply_latency_probe_pods(
        self, nodes: Sequence[KubernetesNode], duration_seconds: int = 600
    ) -> dict[str, str]:
        """Start small node-pinned Pods that a latency probe can exec into."""
        if duration_seconds <= 0:
            raise ValueError("Probe duration must be positive")
        manifests = []
        mapping: dict[str, str] = {}
        for node in nodes:
            hostname = node.labels.get("kubernetes.io/hostname")
            if not hostname:
                raise ValueError(f"Node {node.name!r} lacks kubernetes.io/hostname label")
            suffix = re.sub(r"[^a-z0-9-]+", "-", node.name.lower()).strip("-")[:30] or "node"
            pod_name = f"pac-latency-{suffix}"
            mapping[node.name] = pod_name
            manifests.append({
                "apiVersion": "v1", "kind": "Pod",
                "metadata": {"name": pod_name, "labels": {"app.kubernetes.io/name": "pac-latency-probe"}},
                "spec": {
                    "restartPolicy": "Never",
                    "activeDeadlineSeconds": duration_seconds,
                    "nodeSelector": {"kubernetes.io/hostname": hostname},
                    "securityContext": {
                        "runAsUser": 10000, "runAsGroup": 10000,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [{
                        "name": "probe", "image": "alpine:3.21", "imagePullPolicy": "IfNotPresent",
                        "command": ["/bin/sh", "-ec", f"sleep {duration_seconds}"],
                        "securityContext": {
                            "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]},
                        },
                        "resources": {
                            "requests": {"cpu": "10m", "memory": "16Mi"},
                            "limits": {"cpu": "100m", "memory": "64Mi"},
                        },
                    }],
                },
            })
        if manifests:
            self._run(
                "apply", "--validate=false", "-f", "-",
                input_text=json.dumps({"apiVersion": "v1", "kind": "List", "items": manifests}),
            )
        return mapping

    def clear_latency_probe_pods(self, pod_names: Sequence[str]) -> None:
        for pod_name in pod_names:
            self._run("delete", "pod", pod_name, "--ignore-not-found=true", "--wait=true")

    def clear_background_scenario(self, handle: BackgroundLoadHandle) -> None:
        for pod_name in handle.pod_names:
            self._run("delete", "pod", pod_name, "--ignore-not-found=true", "--wait=true")

    @staticmethod
    def _demo_resources(workload: Mapping[str, object]) -> dict:
        try:
            cpu = Decimal(str(workload["cpu_required"]))
            memory_gib = Decimal(str(workload["memory_required"]))
        except (KeyError, InvalidOperation, TypeError) as exc:
            raise ValueError("Workload must provide numeric cpu_required and memory_required") from exc
        if not cpu.is_finite() or cpu <= 0 or not memory_gib.is_finite() or memory_gib <= 0:
            raise ValueError("Demo workload CPU and memory requirements must be finite and positive")
        millicores = int((cpu * 1000).to_integral_value(rounding=ROUND_CEILING))
        cpu_quantity = f"{millicores}m" if millicores % 1000 else str(millicores // 1000)
        memory_mib = int((memory_gib * 1024).to_integral_value(rounding=ROUND_CEILING))
        memory_quantity = f"{memory_mib}Mi"
        resources = {"cpu": cpu_quantity, "memory": memory_quantity}
        return {"requests": dict(resources), "limits": dict(resources)}

    def create_demo_job(
        self,
        node: KubernetesNode,
        workload: Mapping[str, object],
        duration_seconds: int = 240,
        ttl_seconds: int = 60,
        namespace: str = "default",
    ) -> DemoJobHandle:
        """Create a hardened, scheduler-pinned demo Job on the final selected node."""
        if duration_seconds <= 0 or ttl_seconds <= 0:
            raise ValueError("Demo duration and TTL must be positive")
        hostname = node.labels.get("kubernetes.io/hostname")
        if not hostname:
            raise ValueError(f"Selected node {node.name!r} lacks kubernetes.io/hostname label")
        resources = self._demo_resources(workload)
        suffix = re.sub(r"[^a-z0-9-]+", "-", hostname.lower()).strip("-")[:40] or "node"
        job_name = f"pac-demo-{suffix}-{uuid.uuid4().hex[:8]}"
        labels = {"app.kubernetes.io/name": "pac-demo-placement", "pac.io/demo-job": job_name}
        manifest = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": job_name, "namespace": namespace, "labels": labels},
            "spec": {
                "backoffLimit": 0,
                "activeDeadlineSeconds": duration_seconds + 120,
                "ttlSecondsAfterFinished": ttl_seconds,
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "restartPolicy": "Never",
                        "nodeSelector": {"kubernetes.io/hostname": hostname},
                        "securityContext": {
                            "runAsNonRoot": True,
                            "runAsUser": 10000,
                            "runAsGroup": 10000,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "containers": [{
                            "name": "demo",
                            "image": "alpine:3.21",
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["/bin/sh", "-ec", f"sleep {duration_seconds}"],
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "resources": resources,
                        }],
                    },
                },
            },
        }
        self._run("apply", "--validate=false", "-f", "-", input_text=json.dumps(manifest))
        return DemoJobHandle(job_name=job_name, selected_node=node.name, namespace=namespace)

    def wait_for_demo_job(self, handle: DemoJobHandle, timeout_seconds: float = 120) -> DemoJobStatus:
        """Wait until the Job Pod has a scheduler-assigned node or fails/times out."""
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        deadline = time.monotonic() + timeout_seconds
        selector = f"pac.io/demo-job={handle.job_name}"
        last_reason = "The Job Pod has not been scheduled yet"
        while True:
            job = json.loads(self._run("get", "job", handle.job_name, "-n", handle.namespace, "-o", "json"))
            for condition in job.get("status", {}).get("conditions", []):
                if condition.get("type") == "Failed" and condition.get("status") == "True":
                    reason = condition.get("message") or condition.get("reason") or "Job failed"
                    return DemoJobStatus(handle.job_name, "failed", reason=reason)
            response = json.loads(self._run(
                "get", "pods", "-n", handle.namespace, "-l", selector, "-o", "json"
            ))
            pods = response.get("items", [])
            if pods:
                pod = pods[0]
                phase = pod.get("status", {}).get("phase")
                observed_node = pod.get("spec", {}).get("nodeName")
                if observed_node:
                    if observed_node != handle.selected_node:
                        return DemoJobStatus(
                            handle.job_name, "node_mismatch", observed_node,
                            f"Scheduler assigned {observed_node!r}, expected {handle.selected_node!r}",
                        )
                    return DemoJobStatus(handle.job_name, "scheduled", observed_node)
                if phase == "Failed":
                    reason = pod.get("status", {}).get("reason") or "Job Pod failed before scheduling"
                    return DemoJobStatus(handle.job_name, "failed", reason=reason)
                for condition in pod.get("status", {}).get("conditions", []):
                    if condition.get("type") == "PodScheduled" and condition.get("status") == "False":
                        last_reason = condition.get("message") or condition.get("reason") or last_reason
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return DemoJobStatus(handle.job_name, "timeout", reason=last_reason)
            time.sleep(min(self.poll_interval_seconds, remaining))

    def delete_demo_job(self, handle: DemoJobHandle) -> None:
        """Delete a demo Job and its owned Pod immediately."""
        self._run(
            "delete", "job", handle.job_name, "-n", handle.namespace,
            "--ignore-not-found=true", "--wait=true",
        )


class KubectlPodPingProbe:
    """Measure node-to-target ICMP RTT from a running node-pinned probe Pod."""

    source = "node_icmp_rtt"

    def __init__(
        self,
        provider: KubectlKubernetesProvider,
        pod_names_by_node: Mapping[str, str],
        target: str = "1.1.1.1",
        sample_count: int = 3,
        namespace: str = "default",
    ) -> None:
        if sample_count < 1:
            raise ValueError("sample_count must be positive")
        self.provider = provider
        self.pod_names_by_node = dict(pod_names_by_node)
        self.target = target
        self.sample_count = sample_count
        self.namespace = namespace

    def __call__(self, node_name: str) -> float:
        pod_name = self.pod_names_by_node.get(node_name)
        if not pod_name:
            raise MetricsUnavailableError(f"No running latency probe Pod is configured for node {node_name!r}")
        output = self.provider._run(
            "exec", "-n", self.namespace, pod_name, "--", "ping", "-q", "-c",
            str(self.sample_count), "-W", "2", self.target,
        )
        match = re.search(
            r"(?:rtt|round-trip) min/avg/max(?:/[^=]+)?\s*=\s*[\d.]+/([\d.]+)/[\d.]+",
            output,
        )
        if not match:
            raise MetricsUnavailableError(f"Could not parse ping RTT from node {node_name!r}: {output.strip()}")
        return float(match.group(1))
