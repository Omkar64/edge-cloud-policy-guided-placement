"""Create grouped means and standard deviations from raw trial CSV."""
import argparse
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "results/raw/experiments.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "results/processed/summary.csv")
    args = parser.parse_args()
    if not args.input.exists(): parser.error(f"Input CSV does not exist: {args.input}")
    df = pd.read_csv(args.input)
    metrics = [c for c in df.select_dtypes(include="number").columns if c not in {"seed", "node_count"}]
    grouped = df.groupby(["scenario", "node_count"], dropna=False)[metrics].agg(["mean", "std", "count"])
    grouped.columns = [f"{metric}_{stat}" for metric, stat in grouped.columns]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    grouped.reset_index().to_csv(args.output, index=False)
    print(f"Summary written to {args.output} ({len(grouped)} scenario/node-count groups)")


if __name__ == "__main__": main()
