"""Generate descriptive plots from raw experiment data using matplotlib."""
import argparse
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
import matplotlib.pyplot as plt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "results/raw/experiments.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results/plots")
    args = parser.parse_args()
    if not args.input.exists(): parser.error(f"Input CSV does not exist: {args.input}")
    data = pd.read_csv(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    grouped = data.groupby(["scenario", "node_count"], as_index=False).mean(numeric_only=True)
    def save(name: str, title: str, ylabel: str, series: dict[str, str], percent=False):
        fig, ax = plt.subplots(figsize=(8, 5))
        for scenario, part in grouped.groupby("scenario"):
            for col, label in series.items():
                ax.plot(part["node_count"], part[col] * (100 if percent else 1), marker="o", label=f"{scenario}: {label}")
        ax.set(title=title, xlabel="Node count", ylabel=ylabel)
        ax.grid(True, alpha=.25); ax.legend(fontsize=7); fig.tight_layout()
        fig.savefig(args.output_dir / name, dpi=160); plt.close(fig)
    save("decision_time.png", "Decision time by infrastructure size", "Seconds", {"baseline_decision_time":"baseline", "proposed_total_decision_time":"policy-guided"})
    save("policy_time.png", "OPA evaluation time", "Seconds", {"policy_evaluation_time":"OPA"})
    save("candidate_reduction.png", "Candidate reduction", "Candidates filtered (%)", {"candidate_reduction_percent":"reduction"})
    save("sla_violations.png", "SLA violation rate", "Violation rate (%)", {"baseline_sla_violation":"baseline", "proposed_sla_violation":"policy-guided"}, percent=True)
    save("placement_success.png", "Placement success rate", "Success rate (%)", {"baseline_placement_success":"baseline", "proposed_placement_success":"policy-guided"}, percent=True)
    save("candidate_counts.png", "Candidate counts before and after filtering", "Mean candidate count", {"total_candidates":"before policy", "feasible_candidates":"after policy"})
    save("scoring_time.png", "Scoring time by infrastructure size", "Seconds", {"baseline_scoring_time":"baseline", "proposed_scoring_time":"policy-guided"})
    print(f"Plots saved under {args.output_dir}")


if __name__ == "__main__": main()
