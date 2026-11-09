"""Offline tests for Phase 2 adapters, interfaces, configuration, and mock load state."""
from datetime import datetime, timezone
import json
from io import BytesIO
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from algorithms.feasibility import check_feasibility
from algorithms.weighted_scoring import select_best_node
from cloud.background_scenarios import example_node_heterogeneity
from cloud.background_stress import build_background_stress_pods
from cloud.config import CloudConfig
from cloud.interfaces import KubernetesProvider, MetricsProvider, NodeProvider
from cloud.node_adapter import KubernetesNodeAdapter, MetricsUnavailableError, NodeAdaptationError, parse_cpu_quantity, parse_memory_quantity
from cloud.providers.kubernetes_node_provider import KubernetesNodeProvider
from cloud.providers.kubectl_provider import KubectlKubernetesProvider, KubectlPodPingProbe
from cloud.providers.mock_provider import MockKubernetesProvider, MockMetricsProvider, MockNodeProvider
from cloud.types import KubernetesNode, NodeMetrics
from orchestration.policy_guided_placement import OPAClient


def fresh_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def fixture_node(name: str, node_type: str = "edge") -> KubernetesNode:
    return KubernetesNode(
        name=name,
        labels={"pac.io/node-type": node_type, "pac.io/security-level": "high",
                "node.kubernetes.io/instance-type": "t3.medium",
                "topology.kubernetes.io/zone": "us-east-1a", "kubernetes.io/hostname": name},
        capacity={"cpu": "4", "memory": "16Gi"},
        allocatable={"cpu": "3900m", "memory": "15Gi"},
    )


def fixture_metrics(cpu: str = "500m", memory: str = "2Gi", latency: float = 12.5) -> NodeMetrics:
    return NodeMetrics(cpu, memory, latency, sampled_at=fresh_timestamp())


def fixture_config() -> CloudConfig:
    # Deliberately test fixture data only; never used as an AWS price assertion.
    return CloudConfig(region="test-region-1", cost_usd_per_hour_by_instance_type={"t3.medium": 0.05})


class CloudAbstractionTests(unittest.TestCase):
    def test_kubernetes_node_adapter_produces_phase1_schema(self):
        node = KubernetesNodeAdapter(fixture_config()).adapt(fixture_node("worker-a"), fixture_metrics())
        self.assertEqual(node["id"], "worker-a")
        self.assertEqual(node["type"], "edge")
        self.assertEqual(node["cpu_capacity"], 4.0)
        self.assertEqual(node["memory_capacity"], 16.0)
        self.assertAlmostEqual(node["cpu_utilization"], 12.5)
        self.assertAlmostEqual(node["memory_utilization"], 12.5)
        self.assertEqual(node["latency"], 12.5)
        self.assertEqual(node["security"], "high")
        self.assertEqual(node["cost"], 0.05)
        self.assertEqual(node["cost_unit"], "usd_per_hour_estimate")
        self.assertEqual(node["latency_source"], "node_probe_rtt")

    def test_resource_quantity_conversion(self):
        self.assertEqual(parse_cpu_quantity("250m"), 0.25)
        self.assertEqual(parse_cpu_quantity("2"), 2)
        self.assertEqual(parse_memory_quantity("1Gi"), 1024**3)
        self.assertEqual(parse_memory_quantity("512Mi"), 512 * 1024**2)

    def test_missing_or_stale_metrics_fail_closed(self):
        adapter = KubernetesNodeAdapter(fixture_config())
        with self.assertRaises(MetricsUnavailableError):
            adapter.adapt(fixture_node("worker-a"), NodeMetrics("500m", "2Gi", 10))
        stale = NodeMetrics("500m", "2Gi", 10, sampled_at="2000-01-01T00:00:00+00:00")
        with self.assertRaisesRegex(MetricsUnavailableError, "stale"):
            adapter.adapt(fixture_node("worker-a"), stale)
        missing_metrics = MockKubernetesProvider([fixture_node("worker-a")], {})
        with self.assertRaisesRegex(MetricsUnavailableError, "Metrics unavailable"):
            KubernetesNodeProvider(missing_metrics, fixture_config()).get_nodes()

    def test_security_and_cost_configuration_are_required(self):
        adapter = KubernetesNodeAdapter(fixture_config())
        low_security = fixture_node("worker-a")
        low_security.labels["pac.io/security-level"] = "unclassified"
        with self.assertRaisesRegex(NodeAdaptationError, "security"):
            adapter.adapt(low_security, fixture_metrics())
        unknown_cost = fixture_node("worker-a")
        unknown_cost.labels["node.kubernetes.io/instance-type"] = "unconfigured.type"
        with self.assertRaisesRegex(NodeAdaptationError, "No configured"):
            adapter.adapt(unknown_cost, fixture_metrics())

    def test_toml_cost_configuration(self):
        content = '[aws]\nregion="test-region-1"\n[cost_usd_per_hour]\n"t3.medium"=0.05\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(content, encoding="utf-8")
            loaded = CloudConfig.from_toml(path)
        self.assertEqual(loaded.region, "test-region-1")
        self.assertEqual(loaded.cost_usd_per_hour_by_instance_type["t3.medium"], 0.05)

    def test_interfaces_and_mock_providers(self):
        nodes = [fixture_node("worker-a")]
        metrics = {"worker-a": fixture_metrics()}
        k8s = MockKubernetesProvider(nodes, metrics)
        self.assertIsInstance(k8s, KubernetesProvider)
        node_provider = KubernetesNodeProvider(k8s, fixture_config())
        self.assertIsInstance(node_provider, NodeProvider)
        mock_nodes = MockNodeProvider(node_provider.get_nodes())
        mock_metrics = MockMetricsProvider(metrics)
        self.assertIsInstance(mock_nodes, NodeProvider)
        self.assertIsInstance(mock_metrics, MetricsProvider)
        self.assertEqual(mock_nodes.get_nodes()[0]["id"], "worker-a")
        self.assertIn("worker-a", mock_metrics.get_node_metrics())

    def test_live_kubectl_provider_reads_metrics_and_requires_measured_latency(self):
        node_payload = {"items": [{
            "metadata": {"name": "worker-a", "labels": fixture_node("worker-a").labels},
            "status": {"capacity": fixture_node("worker-a").capacity,
                       "allocatable": fixture_node("worker-a").allocatable},
        }]}
        metrics_payload = {"items": [{
            "metadata": {"name": "worker-a"}, "timestamp": fresh_timestamp(),
            "usage": {"cpu": "250m", "memory": "512Mi"},
        }]}
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            response = node_payload if command[-3:] == ["nodes", "-o", "json"] else metrics_payload
            return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

        source = KubectlKubernetesProvider(
            kubeconfig="test-kubeconfig", latency_probe=lambda name: 13.5, command_runner=runner
        )
        self.assertIsInstance(source, KubernetesProvider)
        self.assertEqual(source.list_nodes()[0].name, "worker-a")
        observed = source.get_node_metrics(["worker-a"])["worker-a"]
        self.assertEqual(observed.cpu_usage, "250m")
        self.assertEqual(observed.memory_usage, "512Mi")
        self.assertEqual(observed.latency_ms, 13.5)
        self.assertEqual(observed.latency_source, "injected_node_probe")
        self.assertEqual(calls[0][1:3], ["--kubeconfig", "test-kubeconfig"])

        missing_probe = KubectlKubernetesProvider(command_runner=runner)
        with self.assertRaisesRegex(MetricsUnavailableError, "latency probe"):
            missing_probe.get_node_metrics(["worker-a"])

    def test_kubectl_ping_probe_extracts_measured_average_rtt(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(
                command, 0, "round-trip min/avg/max = 0.050/0.100/0.150 ms\n", ""
            )

        source = KubectlKubernetesProvider(command_runner=runner)
        probe = KubectlPodPingProbe(source, {"worker-a": "probe-worker-a"})
        self.assertEqual(probe("worker-a"), 0.1)

    def test_kubectl_provider_builds_and_clears_node_pinned_probe_pods(self):
        captured = []

        def runner(command, **kwargs):
            payload = json.loads(kwargs["input"]) if kwargs.get("input") else None
            captured.append((command, payload))
            return subprocess.CompletedProcess(command, 0, "", "")

        source = KubectlKubernetesProvider(command_runner=runner)
        mapping = source.apply_latency_probe_pods([fixture_node("worker-a")], duration_seconds=120)
        pod_name = mapping["worker-a"]
        manifest = captured[0][1]["items"][0]
        self.assertEqual(manifest["metadata"]["name"], pod_name)
        self.assertEqual(manifest["spec"]["nodeSelector"], {"kubernetes.io/hostname": "worker-a"})
        self.assertEqual(manifest["spec"]["containers"][0]["resources"]["limits"]["memory"], "64Mi")
        source.clear_latency_probe_pods(list(mapping.values()))
        self.assertIn(["kubectl", "delete", "pod", pod_name, "--ignore-not-found=true", "--wait=true"],
                      [entry[0] for entry in captured])

    def test_background_scenario_sets_and_restores_heterogeneity(self):
        nodes = [fixture_node(name) for name in ("node-a", "node-b", "node-c")]
        metrics = {node.name: fixture_metrics() for node in nodes}
        provider = MockKubernetesProvider(nodes, metrics)
        scenario = example_node_heterogeneity("node-a", "node-b", "node-c")
        handle = provider.apply_background_scenario(scenario)
        self.assertTrue(handle.mock_only)
        adapted = {node["id"]: node for node in KubernetesNodeProvider(provider, fixture_config()).get_nodes()}
        self.assertAlmostEqual(adapted["node-a"]["cpu_utilization"], 80)
        self.assertAlmostEqual(adapted["node-b"]["memory_utilization"], 90)
        self.assertAlmostEqual(adapted["node-c"]["cpu_utilization"], 12.5)
        provider.clear_background_scenario(handle)
        restored = KubernetesNodeProvider(provider, fixture_config()).get_nodes()
        self.assertAlmostEqual(restored[0]["cpu_utilization"], 12.5)

    def test_stress_pod_manifests_are_pinned_and_bounded(self):
        nodes = [fixture_node(name) for name in ("node-a", "node-b", "node-c")]
        scenario = example_node_heterogeneity("node-a", "node-b", "node-c")
        pods = build_background_stress_pods(nodes, scenario)
        self.assertEqual(len(pods), 2)
        self.assertEqual(pods[0]["spec"]["nodeSelector"], {"kubernetes.io/hostname": "node-a"})
        self.assertIn("yes >/dev/null", pods[0]["spec"]["containers"][0]["command"][2])
        self.assertIn("dd if=/dev/zero", pods[1]["spec"]["containers"][0]["command"][2])
        self.assertNotIn("node-c", [pod["metadata"]["name"] for pod in pods])
        self.assertIn("limits", pods[1]["spec"]["containers"][0]["resources"])
        memory_limit = parse_memory_quantity(pods[1]["spec"]["volumes"][0]["emptyDir"]["sizeLimit"])
        allocatable = parse_memory_quantity(nodes[1].allocatable["memory"])
        self.assertLessEqual(memory_limit, allocatable * 75 / 100)
        self.assertGreaterEqual(pods[1]["spec"]["activeDeadlineSeconds"], 600)

    def test_adapted_nodes_work_with_phase1_feasibility_and_scoring(self):
        raw_nodes = [fixture_node("worker-a"), fixture_node("worker-b", "cloud")]
        metrics = {node.name: fixture_metrics() for node in raw_nodes}
        nodes = KubernetesNodeProvider(MockKubernetesProvider(raw_nodes, metrics), fixture_config()).get_nodes()
        workload = {"cpu_required": 1, "memory_required": 2, "max_latency": 50,
                    "max_cpu_utilization": 80, "max_memory_utilization": 80,
                    "max_cost": 1, "required_security": "high"}
        self.assertTrue(all(check_feasibility(node, workload) for node in nodes))
        selected, score = select_best_node(nodes, normalization_nodes=nodes)
        self.assertIsNotNone(selected)
        self.assertIsNotNone(score)
        required = {"id", "type", "cpu_capacity", "memory_capacity", "cpu_utilization",
                    "memory_utilization", "latency", "cost", "security"}
        self.assertTrue(required.issubset(selected))

    def test_adapted_node_schema_is_accepted_by_phase1_opa_client(self):
        node = KubernetesNodeAdapter(fixture_config()).adapt(fixture_node("worker-a"), fixture_metrics())
        payload = json.dumps({"result": [{"id": "worker-a", "allowed": True, "reasons": []}]}).encode()

        class FakeResponse(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_args): self.close()

        with patch("orchestration.policy_guided_placement.urlopen", return_value=FakeResponse(payload)):
            allowed, _elapsed, rejected = OPAClient("http://opa.invalid").evaluate(
                [node], {"cpu_required": 1, "memory_required": 1})
        self.assertEqual([candidate["id"] for candidate in allowed], ["worker-a"])
        self.assertEqual(rejected, {})


if __name__ == "__main__":
    unittest.main()
