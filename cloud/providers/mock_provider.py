"""Deterministic mock providers. Their metrics are fixtures, never cloud observations."""
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from datetime import datetime, timezone
from copy import deepcopy
from cloud.node_adapter import MetricsUnavailableError, parse_cpu_quantity, parse_memory_quantity
from cloud.types import BackgroundLoadHandle, BackgroundScenario, KubernetesNode, NodeMetrics


class MockNodeProvider:
    def __init__(self, nodes: Sequence[dict]):
        self._nodes = deepcopy(list(nodes))

    def get_nodes(self) -> list[dict]:
        return deepcopy(self._nodes)


class MockMetricsProvider:
    def __init__(self, metrics: Mapping[str, NodeMetrics]):
        self._metrics = dict(metrics)

    def get_node_metrics(self, node_names: Sequence[str] | None = None) -> dict[str, NodeMetrics]:
        if node_names is None:
            return dict(self._metrics)
        unknown = set(node_names) - self._metrics.keys()
        if unknown:
            raise MetricsUnavailableError(f"Metrics unavailable in mock fixtures for node(s): {', '.join(sorted(unknown))}")
        return {name: self._metrics[name] for name in node_names}


class MockKubernetesProvider:
    """Kubernetes API test double with reversible, explicitly synthetic load scenarios."""
    def __init__(self, nodes: Sequence[KubernetesNode], metrics: Mapping[str, NodeMetrics]):
        self._nodes = list(nodes)
        self._metrics = dict(metrics)
        self._active_handle: BackgroundLoadHandle | None = None
        self._before_scenario: dict[str, NodeMetrics] | None = None

    def list_nodes(self) -> list[KubernetesNode]:
        return list(self._nodes)

    def get_node_metrics(self, node_names: Sequence[str] | None = None) -> dict[str, NodeMetrics]:
        if node_names is None:
            return dict(self._metrics)
        missing = set(node_names) - self._metrics.keys()
        if missing:
            raise MetricsUnavailableError(f"Metrics unavailable in mock fixtures for node(s): {', '.join(sorted(missing))}")
        return {name: self._metrics[name] for name in node_names}

    def apply_background_scenario(self, scenario: BackgroundScenario) -> BackgroundLoadHandle:
        if self._active_handle is not None:
            raise RuntimeError("Clear the active mock background scenario before applying another")
        if scenario.duration_seconds <= 0:
            raise ValueError("Background scenario duration must be positive")
        by_name = {node.name: node for node in self._nodes}
        unknown = set(scenario.node_targets) - by_name.keys()
        if unknown:
            raise KeyError(f"Background scenario references unknown node(s): {', '.join(sorted(unknown))}")
        for name, target in scenario.node_targets.items():
            if target.cpu_utilization_percent is not None and not 0 <= target.cpu_utilization_percent <= 100:
                raise ValueError(f"CPU target for {name!r} must be between 0 and 100 percent")
            if target.memory_utilization_percent is not None and not 0 <= target.memory_utilization_percent <= 100:
                raise ValueError(f"Memory target for {name!r} must be between 0 and 100 percent")
            if target.latency_ms is not None and target.latency_ms < 0:
                raise ValueError(f"Latency target for {name!r} must be non-negative")
        updated_metrics = dict(self._metrics)
        for name, target in scenario.node_targets.items():
            node = by_name[name]
            current = updated_metrics[name]
            cpu_pct = target.cpu_utilization_percent
            mem_pct = target.memory_utilization_percent
            if cpu_pct is not None:
                capacity = parse_cpu_quantity(node.capacity["cpu"])
                current = replace(current, cpu_usage=f"{capacity * Decimal(str(cpu_pct)) / 100 * 1000}m")
            if mem_pct is not None:
                capacity = parse_memory_quantity(node.capacity["memory"])
                usage = capacity * Decimal(str(mem_pct)) / 100
                current = replace(current, memory_usage=str(int(usage)))
            if target.latency_ms is not None:
                current = replace(current, latency_ms=target.latency_ms,
                                  latency_source="mock_scenario_fixture")
            if target.cpu_utilization_percent is not None or target.memory_utilization_percent is not None:
                current = replace(current, sampled_at=datetime.now(timezone.utc).isoformat())
            updated_metrics[name] = current
        self._before_scenario = dict(self._metrics)
        self._metrics = updated_metrics
        handle = BackgroundLoadHandle(scenario_name=scenario.name, mock_only=True)
        self._active_handle = handle
        return handle

    def clear_background_scenario(self, handle: BackgroundLoadHandle) -> None:
        if self._active_handle != handle or self._before_scenario is None:
            raise ValueError("Background scenario handle is not active on this mock provider")
        self._metrics = self._before_scenario
        self._before_scenario = None
        self._active_handle = None
