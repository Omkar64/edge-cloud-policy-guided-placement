"""Named experiment scenarios and descriptions."""
SCENARIOS = {
    "normal": "Reference heterogeneous infrastructure and moderate SLA.",
    "edge_overload": "Edge nodes have elevated utilization and tighter utilization limits.",
    "high_latency": "Node latency is shifted upward and the workload latency bound is tighter.",
    "high_cost": "Cloud proportion/costs rise and the workload cost bound is tighter.",
    "strict_sla": "Tight latency, utilization, cost, resource, and security requirements.",
}
