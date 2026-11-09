"""Scenario-aware workload generation."""
import random


def generate_workload(seed: int = 42, scenario: str = "normal") -> dict:
    if scenario not in {"normal", "edge_overload", "high_latency", "high_cost", "strict_sla"}:
        raise ValueError(f"Unknown scenario: {scenario}")
    rng = random.Random(seed ^ 0x5A17)
    workload = {"id": f"microservice-{seed:06d}", "cpu_required": rng.choice([1, 2, 3, 4]),
                "memory_required": rng.choice([2, 4, 8]), "max_latency": 50,
                "max_cpu_utilization": 80, "max_memory_utilization": 80, "max_cost": 4,
                "required_security": "high"}
    if scenario == "high_latency":
        workload["max_latency"] = 35
    elif scenario == "high_cost":
        workload["max_cost"] = 2
    elif scenario == "strict_sla":
        workload.update(cpu_required=4, memory_required=8, max_latency=25,
                        max_cpu_utilization=65, max_memory_utilization=65, max_cost=3)
    elif scenario == "edge_overload":
        workload.update(max_cpu_utilization=65, max_memory_utilization=65)
    return workload
