"""Tests for policy-selected, temporary Kubernetes demo Job placement."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cloud.interfaces import WorkloadPlacementProvider
from cloud.providers.kubectl_provider import KubectlKubernetesProvider
from cloud.types import BackgroundLoadHandle, DemoJobHandle, DemoJobStatus, KubernetesNode
from experiments import run_live_cloud


def fixture_node(name: str, node_type: str) -> KubernetesNode:
    return KubernetesNode(
        name=name,
        labels={
            "pac.io/node-type": node_type,
            "pac.io/security-level": "high",
            "node.kubernetes.io/instance-type": "t3.medium",
            "topology.kubernetes.io/zone": "us-east-1a",
            "kubernetes.io/hostname": name,
        },
        capacity={"cpu": "2", "memory": "4Gi"},
        allocatable={"cpu": "1900m", "memory": "3500Mi"},
    )


class KubectlDemoJobTests(unittest.TestCase):
    def test_demo_job_manifest_is_bounded_pinned_hardened_and_ttl_cleaned(self):
        captured = []

        def runner(command, **kwargs):
            captured.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "job/demo created\n", "")

        provider = KubectlKubernetesProvider(command_runner=runner)
        self.assertIsInstance(provider, WorkloadPlacementProvider)
        selected = fixture_node("worker-cloud", "cloud")
        handle = provider.create_demo_job(
            selected,
            {"cpu_required": 0.25, "memory_required": 0.25},
            duration_seconds=240,
            ttl_seconds=60,
        )
        manifest = json.loads(captured[0][1]["input"])
        template = manifest["spec"]["template"]
        container = template["spec"]["containers"][0]
        self.assertEqual(manifest["kind"], "Job")
        self.assertEqual(manifest["spec"]["ttlSecondsAfterFinished"], 60)
        self.assertEqual(manifest["spec"]["backoffLimit"], 0)
        self.assertEqual(template["spec"]["nodeSelector"], {"kubernetes.io/hostname": "worker-cloud"})
        self.assertEqual(container["command"], ["/bin/sh", "-ec", "sleep 240"])
        self.assertEqual(container["resources"]["requests"], {"cpu": "250m", "memory": "256Mi"})
        self.assertEqual(container["resources"]["limits"], container["resources"]["requests"])
        self.assertTrue(template["spec"]["securityContext"]["runAsNonRoot"])
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(handle.selected_node, "worker-cloud")
        self.assertLessEqual(len(handle.job_name), 63)

    def test_wait_for_demo_job_reports_scheduled_mismatch_failure_and_pending(self):
        handle = DemoJobHandle("pac-demo-cloud", "worker-cloud")
        job = {"status": {}}

        def provider_for(pod):
            def runner(command, **kwargs):
                payload = job if "job" in command else {"items": [pod]}
                return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
            return KubectlKubernetesProvider(command_runner=runner, poll_interval_seconds=0)

        scheduled_pod = {"spec": {"nodeName": "worker-cloud"}, "status": {"phase": "Running"}}
        self.assertEqual(provider_for(scheduled_pod).wait_for_demo_job(handle).status, "scheduled")

        wrong_node = {"spec": {"nodeName": "worker-edge"}, "status": {"phase": "Running"}}
        mismatch = provider_for(wrong_node).wait_for_demo_job(handle)
        self.assertEqual(mismatch.status, "node_mismatch")
        self.assertEqual(mismatch.observed_node, "worker-edge")

        pending = {"spec": {}, "status": {"phase": "Pending", "conditions": [{
            "type": "PodScheduled", "status": "False", "reason": "Unschedulable",
            "message": "Insufficient memory",
        }]}}
        timeout = provider_for(pending).wait_for_demo_job(handle, timeout_seconds=0)
        self.assertEqual(timeout.status, "timeout")
        self.assertIn("Insufficient memory", timeout.reason)

        failed_job = {"status": {"conditions": [{
            "type": "Failed", "status": "True", "reason": "DeadlineExceeded",
            "message": "Job deadline exceeded",
        }]}}
        def failed_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, json.dumps(failed_job), "")
        failed = KubectlKubernetesProvider(command_runner=failed_runner).wait_for_demo_job(handle)
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.reason, "Job deadline exceeded")

    def test_delete_demo_job_deletes_job_and_owned_pod(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "deleted\n", "")

        provider = KubectlKubernetesProvider(command_runner=runner)
        handle = DemoJobHandle("pac-demo-cloud", "worker-cloud", "default")
        provider.delete_demo_job(handle)
        self.assertEqual(calls[0], [
            "kubectl", "delete", "job", "pac-demo-cloud", "-n", "default",
            "--ignore-not-found=true", "--wait=true",
        ])


class RunnerPlacementOrderingTests(unittest.TestCase):
    def _run(self, selected_id, observed_status=None):
        edge = fixture_node("worker-edge", "edge")
        cloud = fixture_node("worker-cloud", "cloud")
        calls = []

        class FakeProvider:
            def __init__(self, **_kwargs):
                self.nodes = [edge, cloud]

            def list_nodes(self):
                return self.nodes

            def apply_latency_probe_pods(self, nodes, duration_seconds):
                return {node.name: "probe-" + node.name for node in nodes}

            def _run(self, *args, **_kwargs):
                return ""

            def apply_background_scenario(self, scenario):
                return BackgroundLoadHandle(scenario.name, ("stress-edge", "stress-cloud"))

            def create_demo_job(self, node, workload, **kwargs):
                calls.append(("create", node.name))
                return DemoJobHandle("pac-demo-cloud", node.name)

            def wait_for_demo_job(self, handle, timeout_seconds):
                return observed_status or DemoJobStatus(handle.job_name, "scheduled", handle.selected_node)

            def delete_demo_job(self, handle):
                calls.append(("delete-job", handle.job_name))

            def clear_background_scenario(self, handle):
                calls.append(("clear-stress", handle.scenario_name))

            def clear_latency_probe_pods(self, pod_names):
                calls.append(("clear-probes", tuple(pod_names)))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.toml"
            config_path.write_text(
                '[aws]\nregion="test-region"\n[cost_usd_per_hour]\n"t3.medium"=0.05\n',
                encoding="utf-8",
            )
            workload_path = root / "workload.json"
            workload_path.write_text(json.dumps({
                "cpu_required": 0.25, "memory_required": 0.25, "max_latency": 50,
                "max_cpu_utilization": 80, "max_memory_utilization": 80,
                "max_cost": 1, "required_security": "high",
            }), encoding="utf-8")
            output_path = root / "result.jsonl"
            adapted = [{"id": edge.name}, {"id": cloud.name}]
            selected = next((node for node in adapted if node["id"] == selected_id), None)
            decision = {"selected_node": selected, "rejected": {}, "placement_success": selected is not None}
            fake_provider = FakeProvider()
            with (
                patch.object(run_live_cloud, "KubectlKubernetesProvider", return_value=fake_provider),
                patch.object(run_live_cloud, "KubernetesNodeProvider") as node_provider,
                patch.object(run_live_cloud, "policy_guided_placement",
                             side_effect=lambda *_args: (calls.append(("decision", selected_id)) or decision)),
                patch.object(run_live_cloud.time, "sleep"),
            ):
                node_provider.return_value.get_nodes.return_value = adapted
                result = run_live_cloud.run_live_decision(
                    kubeconfig="unused", config_path=config_path, workload_path=workload_path,
                    output_path=output_path, place_demo=True,
                )
            return result, calls

    def test_only_final_weighted_selection_reaches_placement_provider(self):
        result, calls = self._run("worker-cloud")
        self.assertEqual(calls[0], ("decision", "worker-cloud"))
        self.assertEqual(calls[1], ("create", "worker-cloud"))
        self.assertEqual(result["demo_placement"]["scheduling_status"], "scheduled")
        self.assertNotIn(("delete-job", "pac-demo-cloud"), calls)

    def test_no_selected_node_never_creates_a_job(self):
        result, calls = self._run(None)
        self.assertNotIn("create", [call[0] for call in calls])
        self.assertEqual(result["demo_placement"]["scheduling_status"], "skipped_no_candidate")

    def test_scheduler_node_mismatch_is_recorded_and_job_deleted(self):
        mismatch = DemoJobStatus("pac-demo-cloud", "node_mismatch", "worker-edge", "wrong node")
        result, calls = self._run("worker-cloud", mismatch)
        self.assertEqual(result["demo_placement"]["scheduling_status"], "node_mismatch")
        self.assertEqual(result["demo_placement"]["observed_node"], "worker-edge")
        self.assertIn(("delete-job", "pac-demo-cloud"), calls)


if __name__ == "__main__":
    unittest.main()
