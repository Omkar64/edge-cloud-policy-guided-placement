# Phase 2 cloud abstraction

Cloud code is isolated under `cloud/`. Unit tests use mocks; live operations require an explicitly selected Kubernetes context and are never started implicitly.

- `interfaces.py` defines runtime-checkable `NodeProvider`, `MetricsProvider`, and `KubernetesProvider` protocols.
- `KubernetesNodeAdapter` converts Kubernetes capacity, configured labels/cost estimates, observed usage, and measured latency into the Phase 1 node schema.
- `KubernetesNodeProvider` combines a `KubernetesProvider` with the adapter and fails closed when metrics are missing or stale.
- `KubectlKubernetesProvider` reads nodes with `kubectl get nodes` and CPU/memory from the Metrics Server API. It has no Kubernetes Python SDK dependency. Supply a measured latency probe; it fails closed without one because Metrics Server does not report latency. `KubectlPodPingProbe` measures ICMP RTT to a configured target from a node-pinned running Pod. Its scenario methods apply node-pinned stress Pods and return a cleanup handle.
- `MockKubernetesProvider` and mock node/metrics providers support offline tests. Fixture metrics are synthetic and must never be reported as cloud measurements.
- `background_scenarios.py` defines a three-node profile with one CPU-stressed node, one memory-stressed node, and one idle node. `background_stress.py` builds node-pinned CPU/memory Pod manifests with hard limits. Memory is capped at 75% of node allocatable capacity to leave room for system variation, and the deadline allows time to fill the memory-backed volume.

The live provider makes no AWS API calls and provisions no AWS infrastructure. It requires `kubectl`, an explicitly selected Kubernetes context, and Metrics Server. The latency input is a measured node probe RTT; application response latency is a separate workload outcome. Security labels are experimental classifications, not proof of security. Cost values are estimates that must come from an operator-provided TOML configuration and documented pricing source.

Actual application workload placement remains opt-in. Stress pods run only when `apply_background_scenario` is explicitly called and can be removed with the returned handle.

## Live policy-only run

`experiments/run_live_cloud.py` requires an explicit kubeconfig, a completed copy of `config.example.toml` with current cost estimates, a workload JSON file, Metrics Server, and a reachable OPA endpoint. It creates short-lived ping and stress Pods, samples after stabilization, runs OPA filtering followed by the existing weighted scorer, appends a JSON result, and removes its temporary probe/stress Pods. By default it only recommends a node. With `--place-demo`, it passes only the scorer's final selected node to the placement provider, creates a hardened four-minute Alpine Job with a 60-second completion TTL, and verifies the scheduler-assigned node. Failed or mismatched placements are deleted immediately; successful Jobs finish and are then removed by the TTL controller. It never places the user's application workload. `workload.example.json` is an example input and should be adjusted to the experiment's workload and thresholds.

```powershell
.venv-phase2\Scripts\python.exe experiments\run_live_cloud.py `
  --kubeconfig "$env:TEMP\pac-phase2-kubeconfig" `
  --config cloud\config.toml `
  --workload cloud\workload.example.json
```

Add `--place-demo` to opt into the temporary Job placement check. The workload JSON's `cpu_required` and `memory_required` values become the Job's CPU and memory requests and limits. The runner still does not create a Service, Deployment, or application workload.
