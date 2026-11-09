"""Typed data models shared by cloud providers, adapters, and local mocks."""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class KubernetesNode:
    """Small provider-neutral projection of a Kubernetes Node API object."""
    name: str
    labels: dict[str, str]
    capacity: dict[str, str]
    allocatable: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_api_object(cls, value: dict[str, Any]) -> "KubernetesNode":
        metadata = value.get("metadata", {})
        status = value.get("status", {})
        return cls(
            name=metadata["name"],
            labels=dict(metadata.get("labels", {})),
            capacity=dict(status.get("capacity", {})),
            allocatable=dict(status.get("allocatable", {})),
        )


@dataclass(frozen=True)
class NodeMetrics:
    """Observed node usage. CPU uses Kubernetes quantity syntax; memory uses bytes/units."""
    cpu_usage: str
    memory_usage: str
    latency_ms: float
    sampled_at: str | None = None
    latency_source: str = "node_probe_rtt"


@dataclass(frozen=True)
class NodeLoadTarget:
    """Explicit test/stress target; percentages are configuration, never cloud telemetry."""
    cpu_utilization_percent: float | None = None
    memory_utilization_percent: float | None = None
    latency_ms: float | None = None


@dataclass(frozen=True)
class BackgroundScenario:
    """Named heterogeneous background state keyed by Kubernetes node name."""
    name: str
    node_targets: dict[str, NodeLoadTarget]
    duration_seconds: int = 180


@dataclass(frozen=True)
class BackgroundLoadHandle:
    scenario_name: str
    pod_names: tuple[str, ...] = ()
    mock_only: bool = False


@dataclass(frozen=True)
class DemoJobHandle:
    """Identity and intended destination for a temporary demo Kubernetes Job."""
    job_name: str
    selected_node: str
    namespace: str = "default"


@dataclass(frozen=True)
class DemoJobStatus:
    """Observed scheduling result for a temporary demo Job."""
    job_name: str
    status: str
    observed_node: str | None = None
    reason: str | None = None

