"""Compose Kubernetes node discovery and observed metrics into Phase 1 nodes."""
from collections.abc import Mapping, Sequence
from cloud.config import CloudConfig
from cloud.interfaces import KubernetesProvider
from cloud.node_adapter import KubernetesNodeAdapter, MetricsUnavailableError
from cloud.types import KubernetesNode, NodeMetrics


class KubernetesNodeProvider:
    """Adapter-backed NodeProvider; missing per-node metrics are a hard, explicit error."""
    def __init__(self, source: KubernetesProvider, config: CloudConfig):
        self.source = source
        self.adapter = KubernetesNodeAdapter(config)

    def list_nodes(self) -> list[KubernetesNode]:
        return self.source.list_nodes()

    def get_node_metrics(self, node_names: Sequence[str] | None = None) -> Mapping[str, NodeMetrics]:
        return self.source.get_node_metrics(node_names)

    def get_nodes(self) -> list[dict]:
        raw_nodes = self.source.list_nodes()
        metrics = self.source.get_node_metrics([node.name for node in raw_nodes])
        missing = [node.name for node in raw_nodes if node.name not in metrics]
        if missing:
            raise MetricsUnavailableError(f"Metrics unavailable for Kubernetes node(s): {', '.join(missing)}")
        return [self.adapter.adapt(node, metrics[node.name]) for node in raw_nodes]
