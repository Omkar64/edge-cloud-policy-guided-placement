"""OPA-backed batch policy evaluation and policy-guided placement."""
import json
import os
from time import perf_counter
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen
from algorithms.weighted_scoring import select_best_node


class OPAClient:
    def __init__(self, url: str | None = None, timeout: float = 30.0):
        self.url = (url or os.getenv("OPA_URL", "http://localhost:8181")).rstrip("/")
        self.timeout = timeout

    def evaluate(self, nodes: list[dict], workload: dict) -> tuple[list[dict], float, dict[str, list[str]]]:
        payload = json.dumps({"input": {"nodes": nodes, "workload": workload}}).encode("utf-8")
        request = Request(f"{self.url}/v1/data/placement/decisions", data=payload,
                          headers={"Content-Type": "application/json"}, method="POST")
        started = perf_counter()
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot query OPA at {self.url}. Start OPA with policies/placement.rego loaded. Details: {exc}") from exc
        elapsed = perf_counter() - started
        try:
            decisions = body["result"]
            if len(decisions) != len(nodes):
                raise ValueError("OPA returned an unexpected decision count")
            by_id = {decision["id"]: decision for decision in decisions}
            allowed = [node for node in nodes if by_id[node["id"]]["allowed"]]
            rejected = {node["id"]: by_id[node["id"]]["reasons"] for node in nodes if not by_id[node["id"]]["allowed"]}
            return allowed, elapsed, rejected
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"OPA response did not match the placement decision schema: {exc}") from exc


def policy_guided_placement(nodes: list[dict], workload: dict, client: OPAClient | None = None) -> dict:
    client = client or OPAClient()
    feasible, policy_time, rejected = client.evaluate(nodes, workload)
    started = perf_counter()
    selected, score = select_best_node(feasible, normalization_nodes=nodes)
    scoring_time = perf_counter() - started
    total = policy_time + scoring_time
    return {"selected_node": selected, "score": score, "policy_evaluation_time": policy_time,
            "scoring_time": scoring_time, "decision_time": total, "feasible_nodes": feasible,
            "rejected": rejected, "evaluated_count": len(nodes), "allowed_count": len(feasible),
            "rejected_count": len(rejected), "placement_success": selected is not None}
