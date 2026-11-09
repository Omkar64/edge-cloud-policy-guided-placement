"""Live OPA policy tests; automatically skipped when OPA is not running."""
import os
import unittest
from urllib.request import urlopen
from urllib.error import URLError
from orchestration.policy_guided_placement import OPAClient, policy_guided_placement

OPA_URL = os.getenv("OPA_URL", "http://localhost:8181")
try:
    with urlopen(OPA_URL + "/health", timeout=1):
        OPA_AVAILABLE = True
except (URLError, TimeoutError, OSError):
    OPA_AVAILABLE = False


@unittest.skipUnless(OPA_AVAILABLE, "Start OPA with policies/placement.rego to run live policy tests")
class OPATests(unittest.TestCase):
    def setUp(self):
        self.node = {"id":"n1", "type":"edge", "cpu_capacity":8, "memory_capacity":16,
                     "cpu_utilization":25, "memory_utilization":25, "latency":10, "cost":1, "security":"high"}
        self.workload = {"cpu_required":2, "memory_required":4, "max_latency":20,
                         "max_cpu_utilization":80, "max_memory_utilization":80,
                         "max_cost":2, "required_security":"high"}

    def test_allow_and_constraint_reasons(self):
        client = OPAClient(OPA_URL)
        allowed, _, rejected = client.evaluate([self.node], self.workload)
        self.assertEqual(len(allowed), 1)
        cases = [("cpu_utilization", 90, "cpu_utilization_exceeded"),
                 ("memory_utilization", 90, "memory_utilization_exceeded"),
                 ("latency", 30, "latency_exceeded"), ("cost", 4, "cost_exceeded"),
                 ("security", "low", "security_requirement_not_met"),
                 ("cpu_capacity", 1, "insufficient_cpu_capacity"),
                 ("memory_capacity", 1, "insufficient_memory_capacity")]
        for field, value, reason in cases:
            _, _, failures = client.evaluate([self.node | {field:value}], self.workload)
            self.assertIn(reason, failures["n1"])

    def test_no_feasible_candidate_fails_gracefully(self):
        result = policy_guided_placement([self.node | {"latency":100}], self.workload, OPAClient(OPA_URL))
        self.assertFalse(result["placement_success"])
        self.assertIsNone(result["selected_node"])
        self.assertIn("latency_exceeded", result["rejected"]["n1"])


if __name__ == "__main__": unittest.main()
