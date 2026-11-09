"""Deterministic heterogeneous edge/cloud infrastructure generation."""
import random


def generate_nodes(number_of_nodes: int, seed: int = 42, scenario: str = "normal") -> list[dict]:
    if number_of_nodes < 1:
        raise ValueError("number_of_nodes must be at least 1")
    if scenario not in {"normal", "edge_overload", "high_latency", "high_cost", "strict_sla"}:
        raise ValueError(f"Unknown scenario: {scenario}")
    rng = random.Random(seed)
    nodes = []
    for i in range(number_of_nodes):
        edge_probability = 0.7 if scenario != "high_cost" else 0.45
        edge = rng.random() < edge_probability
        if edge:
            kind, latency = "edge", rng.randint(5, 50)
            cpu, memory, cost = rng.choice([4, 8, 16]), rng.choice([8, 16, 32]), rng.randint(1, 3)
        else:
            kind, latency = "cloud", rng.randint(50, 150)
            cpu, memory, cost = rng.choice([16, 32, 64]), rng.choice([32, 64, 128]), rng.randint(4, 8)
        if scenario == "high_latency":
            latency = min(180, latency + (35 if edge else 45))
        if scenario == "high_cost" and not edge:
            cost = min(10, cost + 2)
        utilization_low, utilization_high = (65, 98) if scenario == "edge_overload" and edge else (20, 95)
        security = rng.choice(["medium", "high"])
        nodes.append({"id": f"{kind}-{i + 1:03d}", "type": kind, "cpu_capacity": cpu,
                      "memory_capacity": memory, "cpu_utilization": rng.randint(utilization_low, utilization_high),
                      "memory_utilization": rng.randint(utilization_low, utilization_high), "latency": latency,
                      "cost": cost, "security": security})
    return nodes
