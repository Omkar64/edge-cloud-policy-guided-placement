"""Provider contracts. Implementations may be live Kubernetes providers or explicit mocks."""
from collections.abc import Mapping, Sequence
from typing import Any
from typing import Protocol, runtime_checkable
from cloud.types import (BackgroundLoadHandle, BackgroundScenario, DemoJobHandle,
                         DemoJobStatus, KubernetesNode, NodeMetrics)


@runtime_checkable
class NodeProvider(Protocol):
    def get_nodes(self) -> list[dict]:
        """Return Phase 1-compatible node dictionaries."""
        ...


@runtime_checkable
class MetricsProvider(Protocol):
    def get_node_metrics(self, node_names: Sequence[str] | None = None) -> Mapping[str, NodeMetrics]:
        """Return observed metrics keyed by Kubernetes node name; never synthesize live metrics."""
        ...


@runtime_checkable
class KubernetesProvider(Protocol):
    def list_nodes(self) -> list[KubernetesNode]:
        ...

    def get_node_metrics(self, node_names: Sequence[str] | None = None) -> Mapping[str, NodeMetrics]:
        ...

    def apply_background_scenario(self, scenario: BackgroundScenario) -> BackgroundLoadHandle:
        """Apply configured per-node load and return a cleanup handle."""
        ...

    def clear_background_scenario(self, handle: BackgroundLoadHandle) -> None:
        ...


@runtime_checkable
class WorkloadPlacementProvider(Protocol):
    """Place and observe a bounded demo Job after policy and scoring select a node."""

    def create_demo_job(
        self, node: KubernetesNode, workload: Mapping[str, Any],
        duration_seconds: int = 240, ttl_seconds: int = 60,
    ) -> DemoJobHandle:
        ...

    def wait_for_demo_job(self, handle: DemoJobHandle, timeout_seconds: float = 120) -> DemoJobStatus:
        ...

    def delete_demo_job(self, handle: DemoJobHandle) -> None:
        ...
