"""Run the node-count x scenario repeated experiment matrix."""
import argparse
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.run_experiment import append_row, run_trial
from simulation.scenarios import SCENARIOS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--node-counts", type=int, nargs="+", default=[10, 50, 100, 500, 1000])
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=list(SCENARIOS))
    parser.add_argument("--output", type=Path, default=ROOT / "results/raw/experiments.csv")
    parser.add_argument("--opa-url", default=None)
    args = parser.parse_args()
    if args.repetitions < 1 or any(n < 1 for n in args.node_counts): parser.error("repetitions and node counts must be positive")
    for scenario in args.scenarios:
        for count in args.node_counts:
            for repetition in range(args.repetitions):
                row = run_trial(count, args.seed + repetition, scenario, args.opa_url)
                append_row(args.output, row)
            print(f"Completed scenario={scenario}, nodes={count}, repetitions={args.repetitions}")
    print(f"Raw results appended to {args.output}")


if __name__ == "__main__": main()
