import unittest
from simulation.node_generator import generate_nodes
from simulation.workload_generator import generate_workload
from algorithms.feasibility import check_feasibility, get_feasibility_reasons
from algorithms.weighted_scoring import select_best_node, calculate_score
from orchestration.baseline_placement import baseline_placement


class CoreTests(unittest.TestCase):
    def test_generation_is_deterministic(self):
        self.assertEqual(generate_nodes(10, 9), generate_nodes(10, 9))
        self.assertEqual(generate_workload(9), generate_workload(9))
        self.assertEqual(len(generate_nodes(7)), 7)

    def test_feasibility_constraints(self):
        node = dict(id="n", type="edge", cpu_capacity=8, memory_capacity=16,
                    cpu_utilization=25, memory_utilization=25, latency=10, cost=1, security="high")
        work = dict(cpu_required=2, memory_required=4, max_latency=20, max_cpu_utilization=80,
                    max_memory_utilization=80, max_cost=2, required_security="high")
        self.assertTrue(check_feasibility(node, work))
        for key, value, expected in [("latency", 21, "latency_exceeded"), ("cost", 3, "cost_exceeded"),
                                     ("cpu_utilization", 81, "cpu_utilization_exceeded"),
                                     ("memory_utilization", 81, "memory_utilization_exceeded"),
                                     ("cpu_capacity", 1, "insufficient_cpu_capacity"),
                                     ("memory_capacity", 1, "insufficient_memory_capacity"),
                                     ("security", "low", "security_requirement_not_met")]:
            changed = node | {key: value}
            self.assertIn(expected, get_feasibility_reasons(changed, work))

    def test_scoring_and_baseline(self):
        self.assertEqual(select_best_node([]), (None, None))
        nodes = generate_nodes(8, 2)
        self.assertIsNotNone(select_best_node(nodes)[0])
        self.assertTrue(0 <= calculate_score(nodes[0], nodes) <= 1)
        self.assertTrue(baseline_placement(nodes, generate_workload())["placement_success"])


if __name__ == "__main__": unittest.main()
