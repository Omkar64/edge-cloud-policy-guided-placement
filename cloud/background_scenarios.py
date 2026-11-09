"""Reproducible heterogeneous background-state profiles for mock and live runners."""
from cloud.types import BackgroundScenario, NodeLoadTarget


def example_node_heterogeneity(cpu_node: str, memory_node: str, idle_node: str,
                               duration_seconds: int = 180) -> BackgroundScenario:
    """Node A at 80% CPU, B at 90% memory, C receives no generated background load."""
    if len({cpu_node, memory_node, idle_node}) != 3:
        raise ValueError("CPU-constrained, memory-constrained, and idle nodes must be distinct")
    return BackgroundScenario(
        name="cpu-memory-idle-heterogeneity",
        duration_seconds=duration_seconds,
        node_targets={
            cpu_node: NodeLoadTarget(cpu_utilization_percent=80),
            memory_node: NodeLoadTarget(memory_utilization_percent=90),
            idle_node: NodeLoadTarget(),
        },
    )
