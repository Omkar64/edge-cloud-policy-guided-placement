"""Weighted placement scoring with reusable normalization bounds."""
from collections.abc import Sequence


def normalize(value: float, minimum: float, maximum: float) -> float:
    return 0.0 if maximum == minimum else (value - minimum) / (maximum - minimum)


def calculate_score(node: dict, nodes: Sequence[dict], latency_weight: float = 0.4,
                   cpu_weight: float = 0.3, memory_weight: float = 0.2,
                   cost_weight: float = 0.1) -> float:
    """Lower is better. Bounds come from the supplied shared reference population."""
    if not nodes:
        raise ValueError("Normalization population cannot be empty")
    attributes = (("latency", latency_weight), ("cpu_utilization", cpu_weight),
                  ("memory_utilization", memory_weight), ("cost", cost_weight))
    return sum(weight * normalize(node[key], min(n[key] for n in nodes), max(n[key] for n in nodes))
               for key, weight in attributes)


def select_best_node(candidates: Sequence[dict], normalization_nodes: Sequence[dict] | None = None,
                     **weights) -> tuple[dict | None, float | None]:
    if not candidates:
        return None, None
    reference = normalization_nodes if normalization_nodes is not None else candidates
    scored = [(calculate_score(node, reference, **weights), node) for node in candidates]
    score, node = min(scored, key=lambda pair: (pair[0], pair[1]["id"]))
    return node, score
