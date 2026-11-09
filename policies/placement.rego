package placement

import rego.v1

security_levels := {"low": 1, "medium": 2, "high": 3}

cpu_reasons(node, workload) := ["cpu_utilization_exceeded"] if {
    node.cpu_utilization > workload.max_cpu_utilization
} else := []

memory_reasons(node, workload) := ["memory_utilization_exceeded"] if {
    node.memory_utilization > workload.max_memory_utilization
} else := []

latency_cost_reasons(node, workload) := ["latency_exceeded"] if {
    node.latency > workload.max_latency
} else := []

cost_reasons(node, workload) := ["cost_exceeded"] if {
    node.cost > workload.max_cost
} else := []

capacity_security_reasons(node, workload) := ["insufficient_cpu_capacity"] if {
    node.cpu_capacity * (1 - node.cpu_utilization / 100) < workload.cpu_required
} else := []

decision_for(node, workload) := {"id": node.id, "allowed": count(reasons) == 0, "reasons": reasons} if {
    reasons := array.concat(cpu_reasons(node, workload), array.concat(memory_reasons(node, workload), array.concat(latency_cost_reasons(node, workload), array.concat(cost_reasons(node, workload), array.concat(capacity_security_reasons(node, workload), array.concat(memory_capacity_security_reasons(node, workload), security_reason(node, workload)))))))
}

memory_capacity_security_reasons(node, workload) := ["insufficient_memory_capacity"] if {
    node.memory_capacity * (1 - node.memory_utilization / 100) < workload.memory_required
} else := []

security_reason(node, workload) := ["security_requirement_not_met"] if {
    object.get(security_levels, node.security, 0) < object.get(security_levels, workload.required_security, 0)
} else := []

decisions := [decision_for(node, input.workload) | some node in input.nodes]
