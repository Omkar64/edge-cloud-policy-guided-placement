"""Build node-pinned Kubernetes Pod manifests for later live stress execution.

This module only creates manifest dictionaries. It never contacts Kubernetes or
creates pods. The live provider in a later checkpoint will own apply and cleanup.
"""
import math
import re
from decimal import Decimal
from cloud.node_adapter import parse_cpu_quantity, parse_memory_quantity
from cloud.types import BackgroundScenario, KubernetesNode


class BackgroundStressError(ValueError):
    pass


def build_background_stress_pods(
    nodes: list[KubernetesNode], scenario: BackgroundScenario, image: str = "alpine:3.21"
) -> list[dict]:
    """Create one explicitly configured stress pod per targeted node.

    CPU and memory are hard-limited. Requests are one quarter of target load so
    a pinned stress pod can be scheduled alongside Kubernetes system requests;
    measured actual metrics, not these targets, must be passed to OPA in live runs.
    Memory targets are capped at 75% of allocatable capacity to leave room for
    system and workload variation. The pod deadline includes time to fill tmpfs.
    """
    by_name = {node.name: node for node in nodes}
    unknown = set(scenario.node_targets) - by_name.keys()
    if unknown:
        raise BackgroundStressError(f"Scenario references unknown node(s): {', '.join(sorted(unknown))}")
    if scenario.duration_seconds <= 0:
        raise BackgroundStressError("Scenario duration must be positive")
    manifests = []
    for node_name, target in scenario.node_targets.items():
        if target.cpu_utilization_percent is None and target.memory_utilization_percent is None:
            continue
        if target.latency_ms is not None and target.cpu_utilization_percent is None and target.memory_utilization_percent is None:
            continue
        node = by_name[node_name]
        hostname = node.labels.get("kubernetes.io/hostname")
        if not hostname:
            raise BackgroundStressError(f"Node {node_name!r} lacks kubernetes.io/hostname label")
        cpu_percent = target.cpu_utilization_percent or 0.0
        memory_percent = target.memory_utilization_percent or 0.0
        if not 0 <= cpu_percent <= 95:
            raise BackgroundStressError("Configured CPU stress target must be between 0 and 95 percent")
        if not 0 <= memory_percent <= 90:
            raise BackgroundStressError("Configured memory stress target must be between 0 and 90 percent")
        cpu_capacity = parse_cpu_quantity(node.capacity["cpu"])
        allocatable_memory = parse_memory_quantity(node.allocatable.get("memory", node.capacity["memory"]))
        cpu_millicores = max(0, int(cpu_capacity * 1000 * Decimal(str(cpu_percent)) / 100))
        safe_memory_percent = min(memory_percent, 75.0)
        memory_mib = max(0, int(allocatable_memory / (1024**2) * Decimal(str(safe_memory_percent)) / 100))
        if cpu_percent and cpu_millicores < 10:
            cpu_millicores = 10
        if memory_percent and memory_mib < 1:
            memory_mib = 1
        workers = max(1, math.ceil(cpu_millicores / 1000)) if cpu_millicores else 0
        name_suffix = re.sub(r"[^a-z0-9-]+", "-", node_name.lower()).strip("-")[:30] or "node"
        name = f"pac-stress-{name_suffix}"
        effective_cpu_limit = cpu_millicores if cpu_millicores else (500 if memory_mib else 10)
        cpu_limit = f"{effective_cpu_limit}m"
        cpu_request = f"{max(10, effective_cpu_limit // 4)}m"
        memory_limit_mib = max(64, memory_mib + 64)
        memory_request_mib = max(32, memory_mib // 4)
        cpu_start = f"for i in $(seq 1 {workers}); do yes >/dev/null & done; " if workers else ":; "
        script = (
            "set -eu; " + cpu_start +
            f"if [ {memory_mib} -gt 0 ]; then dd if=/dev/zero of=/dev/shm/pac-stress "
            f"bs=1M count={memory_mib} 2>/dev/null; fi; "
            f"sleep {scenario.duration_seconds}"
        )
        manifests.append({
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": name, "labels": {"app.kubernetes.io/name": "pac-background-stress",
                                                     "pac.io/scenario": scenario.name}},
            "spec": {
                "restartPolicy": "Never", "activeDeadlineSeconds": max(scenario.duration_seconds + 30, 600),
                "nodeSelector": {"kubernetes.io/hostname": hostname},
                "securityContext": {"runAsUser": 10000, "runAsGroup": 10000, "fsGroup": 10000,
                                    "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [{
                    "name": "stress", "image": image, "imagePullPolicy": "IfNotPresent",
                    "command": ["/bin/sh", "-ec", script],
                    "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                        "capabilities": {"drop": ["ALL"]}},
                    "resources": {"requests": {"cpu": cpu_request, "memory": f"{memory_request_mib}Mi"},
                                  "limits": {"cpu": cpu_limit, "memory": f"{memory_limit_mib}Mi"}},
                    "volumeMounts": [{"name": "shm", "mountPath": "/dev/shm"}],
                }],
                "volumes": [{"name": "shm", "emptyDir": {"medium": "Memory", "sizeLimit": f"{max(1, memory_mib)}Mi"}}],
            },
        })
    return manifests
