# Policy-Guided Search-Space Reduction for SLA-Aware Microservice Orchestration

Phase 1 is a reproducible local simulation. It tests whether OPA/Rego hard-constraint filtering reduces candidates while retaining acceptable placement quality. Phase 2 will validate the approach in AWS/Kubernetes; no cloud deployment is implemented here.

**Phase 2 status:** the local abstraction and mock layer is implemented under [`cloud/`](cloud/README.md). It includes Kubernetes-shaped node/metrics adapters, explicit mock background-load scenarios, and node-pinned stress Pod manifest generation. It does not call AWS/Kubernetes or create infrastructure; live providers and deployment are subsequent checkpoints.

The Checkpoint 3 Terraform definition is under [`cloud/aws/terraform/`](cloud/aws/terraform/README.md). It describes a small EKS cluster and Spot worker groups; Terraform `apply` has not been run. Review the cost, network exposure, and cleanup notes before requesting infrastructure creation.

## Research question and hypothesis

Can policy-guided candidate filtering reduce the search space and placement decision overhead while maintaining acceptable placement quality? The hypothesis is that filtering reduces candidates and may reduce decision overhead while keeping SLA compliance and placement quality comparable. Results are empirical; OPA is a constraint filter, not an optimizer, and may add overhead.

## Architecture

Baseline: all simulated nodes → shared weighted scoring → lowest score.

Proposed: all simulated nodes → one batch request to local OPA/Rego → feasible candidates → the same weighted scoring → lowest score.

OPA enforces utilization, latency, cost, available CPU/memory, and security hierarchy (`low < medium < high`). Weighted scoring ranks only; it does not enforce constraints. The baseline deliberately scores every node and can select an SLA-violating node.

## Simulation and experimental design

Infrastructure is heterogeneous edge/cloud. Five deterministic scenarios are available: `normal`, `edge_overload`, `high_latency`, `high_cost`, and `strict_sla`. Both approaches receive the exact same generated nodes and workload for each seed. Node generation uses a local seeded random generator and does not modify global random state.

Default full matrix: 10, 50, 100, 500, and 1000 nodes × five scenarios × 30 seeds (42–71). Metrics include policy and scoring time, total decision time, candidate reduction, placement success, SLA compliance, selected-node attributes, and rejection reasons. Candidate reduction is not a time reduction. Proposed total decision time includes the OPA REST request plus proposed scoring; baseline time is baseline scoring. Process startup is excluded.

Both approaches normalize scoring attributes using bounds from the original full node population. Therefore a candidate’s score uses the same bounds in both methods. Empty candidate sets produce a failed placement with no selected node. A single candidate is scored against full population bounds, avoiding the old all-zero subset normalization effect.

## Setup

Requires Python 3.10+ and OPA 1.x. From this project directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Install the OPA CLI from the official Styra OPA releases for your operating system, then confirm `opa version` works. Start a persistent local OPA server from the project directory:

```powershell
opa run --server --addr localhost:8181 policies/placement.rego
```

Keep that terminal running. The Python client sends one JSON batch to `http://localhost:8181/v1/data/placement/decisions`. Override the endpoint with `--opa-url` or `OPA_URL`. If OPA is unavailable or returns an invalid response, the experiment stops with a descriptive error; Python does not emulate policy evaluation.

## Commands

One trial (also appends one row to raw CSV):

```powershell
python experiments/run_experiment.py --nodes 100 --seed 42 --scenario normal
```

Several paired repetitions:

```powershell
python experiments/run_experiment.py --nodes 100 --seed 42 --scenario strict_sla --repetitions 30 --output results/raw/strict.csv
```

Complete default matrix:

```powershell
python experiments/run_all_experiments.py --repetitions 30
```

Analysis and plots:

```powershell
python analysis/analyze_results.py
python analysis/plots.py
```

Core tests (OPA server required only for actual end-to-end trial commands):

```powershell
python -m unittest discover -s tests -v
```

## Outputs

- `results/raw/experiments.csv`: one row per paired trial, including seed, scenario, node count, timings, decisions, node attributes, SLA indicators, candidate counts, and policy rejection reason names.
- `results/processed/summary.csv`: grouped scenario/node-count means, sample standard deviations, and trial counts for numeric metrics.
- `results/plots/decision_time.png`: baseline and policy-guided decision time as node count grows, by scenario.
- `policy_time.png`: OPA evaluation time by node count.
- `candidate_reduction.png`: percentage of candidates filtered.
- `sla_violations.png`: measured baseline and proposed SLA violation rates.
- `placement_success.png`: placement success rates.
- `candidate_counts.png`: candidates before and after policy filtering.
- `scoring_time.png`: scoring time for both methods.

Plots show means over the available raw rows and do not imply statistical significance. The summary reports standard deviations but does not establish significance. Preserve raw CSVs and seeds when presenting results; rerunning appends rows, so use a new output file when you want a clean dataset.

## Limitations and future work

Local OPA REST latency includes local HTTP/request overhead and is hardware/software dependent. A single workload is evaluated per trial; this does not model scheduling interactions across sequential placements, network variability, or real resource telemetry. Baseline and proposed intentionally answer different questions: baseline ranking alone can violate constraints, while the proposed method only chooses feasible candidates. Interpret SLA and placement quality alongside timing. Validate generated results and policy behavior before drawing conclusions. Phase 2 will evaluate these policies against AWS/Kubernetes infrastructure after Phase 1 validation.
