"""Baseline placement: score every node without policy filtering."""
from time import perf_counter
from algorithms.weighted_scoring import select_best_node


def baseline_placement(nodes: list[dict], workload: dict) -> dict:
    started = perf_counter()
    node, score = select_best_node(nodes, normalization_nodes=nodes)
    elapsed = perf_counter() - started
    return {"selected_node": node, "score": score, "decision_time": elapsed,
            "scoring_time": elapsed, "placement_success": node is not None}
