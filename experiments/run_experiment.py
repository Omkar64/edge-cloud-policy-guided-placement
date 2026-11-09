"""Run a paired baseline/proposed trial and append its metrics to CSV."""
import argparse
import csv
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from algorithms.feasibility import check_feasibility, get_feasibility_reasons
from orchestration.baseline_placement import baseline_placement
from orchestration.policy_guided_placement import policy_guided_placement, OPAClient
from simulation.node_generator import generate_nodes
from simulation.workload_generator import generate_workload
from simulation.scenarios import SCENARIOS



def run_trial(node_count: int, seed: int, scenario: str, opa_url: str | None = None) -> dict:
    nodes = generate_nodes(node_count, seed, scenario)
    workload = generate_workload(seed, scenario)
    baseline = baseline_placement(nodes, workload)
    proposed = policy_guided_placement(nodes, workload, OPAClient(opa_url))
    b, p = baseline["selected_node"], proposed["selected_node"]
    b_ok = bool(b and check_feasibility(b, workload))
    p_ok = bool(p and check_feasibility(p, workload))
    rejected_reasons = sorted({reason for reasons in proposed["rejected"].values() for reason in reasons})
    total, feasible = len(nodes), proposed["allowed_count"]
    row = {"scenario": scenario, "node_count": node_count, "seed": seed,
           "baseline_decision_time": baseline["decision_time"], "baseline_scoring_time": baseline["scoring_time"],
           "baseline_selected_node": b["id"] if b else "", "baseline_score": baseline["score"],
           "baseline_sla_compliant": int(b_ok), "baseline_placement_success": int(baseline["placement_success"]),
           "baseline_sla_violation": int(bool(b and not b_ok)),
           "baseline_sla_violation_reasons": ";".join(get_feasibility_reasons(b, workload)) if b else "no_candidate",
           "proposed_selected_node": p["id"] if p else "", "proposed_score": proposed["score"],
           "proposed_sla_compliant": int(p_ok), "proposed_placement_success": int(proposed["placement_success"]),
           "proposed_sla_violation": int(bool(p and not p_ok)),
           "proposed_sla_violation_reasons": ";".join(get_feasibility_reasons(p, workload)) if p else "no_feasible_node",
           "policy_evaluation_time": proposed["policy_evaluation_time"], "proposed_scoring_time": proposed["scoring_time"],
           "proposed_total_decision_time": proposed["decision_time"], "total_candidates": total,
           "feasible_candidates": feasible, "filtered_candidates": total-feasible,
           "candidate_reduction_percent": 100*(total-feasible)/total if total else 0,
           "policy_allowed_count": proposed["allowed_count"], "policy_rejected_count": proposed["rejected_count"],
           "policy_rejection_reasons": ";".join(rejected_reasons), "placement_success": int(p is not None)}
    for prefix, selected in (("baseline", b), ("proposed", p)):
        for field in ("cost", "latency", "cpu_utilization", "memory_utilization"):
            row[f"{prefix}_{field}"] = selected[field] if selected else ""
    return row


def append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        if not exists: writer.writeheader()
        writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--output", type=Path, default=ROOT / "results/raw/experiments.csv")
    parser.add_argument("--opa-url", default=None)
    args = parser.parse_args()
    if args.nodes < 1 or args.repetitions < 1: parser.error("--nodes and --repetitions must be positive")
    for offset in range(args.repetitions):
        row = run_trial(args.nodes, args.seed + offset, args.scenario, args.opa_url)
        append_row(args.output, row)
        print(f"{args.scenario} | nodes={args.nodes} seed={row['seed']} | baseline={row['baseline_selected_node'] or 'none'} "
              f"({row['baseline_decision_time']:.6f}s) | proposed={row['proposed_selected_node'] or 'none'} "
              f"({row['proposed_total_decision_time']:.6f}s) | feasible={row['feasible_candidates']}/{row['total_candidates']} "
              f"reduction={row['candidate_reduction_percent']:.1f}%")
    print(f"Raw results appended to {args.output}")


if __name__ == "__main__": main()
