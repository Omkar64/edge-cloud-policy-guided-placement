"""Reference Python feasibility checks, used for validation and SLA metrics."""
SECURITY_LEVELS = {"low": 1, "medium": 2, "high": 3}


def get_feasibility_reasons(node: dict, workload: dict) -> list[str]:
    reasons = []
    if node["cpu_utilization"] > workload["max_cpu_utilization"]: reasons.append("cpu_utilization_exceeded")
    if node["memory_utilization"] > workload["max_memory_utilization"]: reasons.append("memory_utilization_exceeded")
    if node["latency"] > workload["max_latency"]: reasons.append("latency_exceeded")
    if node["cost"] > workload["max_cost"]: reasons.append("cost_exceeded")
    if node["cpu_capacity"] * (1 - node["cpu_utilization"] / 100) < workload["cpu_required"]: reasons.append("insufficient_cpu_capacity")
    if node["memory_capacity"] * (1 - node["memory_utilization"] / 100) < workload["memory_required"]: reasons.append("insufficient_memory_capacity")
    if SECURITY_LEVELS.get(node["security"], 0) < SECURITY_LEVELS.get(workload["required_security"], 0): reasons.append("security_requirement_not_met")
    return reasons


def check_feasibility(node: dict, workload: dict) -> bool:
    return not get_feasibility_reasons(node, workload)


def filter_feasible_nodes(nodes: list[dict], workload: dict) -> list[dict]:
    return [node for node in nodes if check_feasibility(node, workload)]
