import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import yaml
from helpers import COLLECTION
from test_ansible_render import ROOT, run_playbook


class ObservabilityTests(unittest.TestCase):
    def test_optional_role_can_be_disabled_without_credentials_or_host_changes(self):
        result = run_playbook(str(ROOT / "tests/playbooks/observability-disabled.yml"))
        self.assertIn("changed=0", result.stdout)

    def test_private_inputs_are_rejected_without_leaking_values(self):
        import os
        import subprocess

        from test_ansible_render import ANSIBLE_PLAYBOOK

        result = subprocess.run(
            [
                str(ANSIBLE_PLAYBOOK),
                str(ROOT / "tests/playbooks/observability-disabled.yml"),
                "-e",
                json.dumps(
                    {
                        "observability_enabled": True,
                        "observability_credentials": {
                            "GRAFANA_CLOUD_TOKEN": "synthetic-private-token"
                        },
                    }
                ),
            ],
            cwd=ROOT,
            env={**os.environ, "ANSIBLE_CONFIG": str(ROOT / "ansible.cfg")},
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("synthetic-private-token", result.stdout + result.stderr)
        self.assertIn("changed=0", result.stdout)

    def test_complete_safe_credentials_pass_the_real_preflight_without_mutations(self):
        # Execute only the real first task so valid credentials cannot install host packages.
        tasks = yaml.safe_load((COLLECTION / "roles/observability/tasks/enabled.yml").read_text())
        credentials = {
            "GRAFANA_CLOUD_METRICS_URL": "https://prometheus-test.grafana.net/api/prom/push",
            "GRAFANA_CLOUD_METRICS_USERNAME": "1",
            "GRAFANA_CLOUD_LOGS_URL": "https://logs-test.grafana.net/loki/api/v1/push",
            "GRAFANA_CLOUD_LOGS_USERNAME": "1",
            "GRAFANA_CLOUD_TOKEN": "synthetic-not-a-real-token",
        }
        with tempfile.TemporaryDirectory() as tmp:
            playbook = Path(tmp) / "preflight.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [
                        {
                            "name": "Verify only collector preflight with synthetic values",
                            "hosts": "localhost",
                            "connection": "local",
                            "gather_facts": False,
                            "vars": {
                                "observability_credentials": credentials,
                                "observability_host_label": "personal-vps",
                            },
                            "tasks": [tasks[0]],
                        }
                    ]
                )
            )
            result = run_playbook(str(playbook))
            self.assertIn("changed=0", result.stdout)
            self.assertNotIn("synthetic-not-a-real-token", result.stdout + result.stderr)

    def test_collector_only_entrypoint_preflights_valid_and_bad_inputs_without_mutation(self):
        import os
        import subprocess

        from test_ansible_render import ANSIBLE_PLAYBOOK

        safe = {
            "GRAFANA_CLOUD_METRICS_URL": "https://prometheus-test.grafana.net/api/prom/push",
            "GRAFANA_CLOUD_METRICS_USERNAME": "1",
            "GRAFANA_CLOUD_LOGS_URL": "https://logs-test.grafana.net/loki/api/v1/push",
            "GRAFANA_CLOUD_LOGS_USERNAME": "1",
            "GRAFANA_CLOUD_TOKEN": "synthetic-not-a-real-token",
        }
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.yml"
            inventory.write_text(
                yaml.safe_dump(
                    {
                        "all": {
                            "children": {
                                "vps": {
                                    "hosts": {
                                        "localhost": {
                                            "ansible_connection": "local",
                                            "ansible_become": False,
                                        }
                                    }
                                }
                            }
                        }
                    }
                )
            )
            for enabled, credentials, success in [
                (False, {}, True),
                (True, safe, True),
                (True, {}, False),
                (True, {**safe, "GRAFANA_CLOUD_TOKEN": "bad\nsecret"}, False),
            ]:
                with self.subTest(enabled=enabled, success=success):
                    arguments = [
                        str(ANSIBLE_PLAYBOOK),
                        "-i",
                        str(inventory),
                        str(ROOT / "playbooks/observability.yml"),
                        "-e",
                        json.dumps(
                            {
                                "vps_observability_enabled": enabled,
                                "observability_credentials": credentials,
                            }
                        ),
                    ]
                    if enabled:
                        arguments += ["--tags", "observability_preflight"]
                    result = subprocess.run(
                        arguments,
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env={**os.environ, "ANSIBLE_CONFIG": str(ROOT / "ansible.cfg")},
                    )
                    self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                    self.assertIn("changed=0", result.stdout)
                    self.assertNotIn("synthetic-not-a-real-token", result.stdout + result.stderr)
                    self.assertNotIn("bad\nsecret", result.stdout + result.stderr)

    def test_bridge_write_timestamp_advances_only_when_collector_replaces_the_file(self):
        from unittest.mock import patch

        path = COLLECTION / "roles/observability/files/platform-metrics.py"
        spec = importlib.util.spec_from_file_location("platform_metrics", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry, output = root / "registry.json", root / "platform.prom"
            registry.write_text(json.dumps({"protocol": 1, "instances": {}}))
            original = module.render_metrics
            # Redirect fixed host paths while preserving real rendering and atomic file writes.
            with (
                patch.object(module, "OUTPUT", output),
                patch.object(
                    module,
                    "render_metrics",
                    side_effect=lambda: original(registry, root / "reboot"),
                ),
            ):
                with patch("time.time", return_value=1793771234):
                    module.main()
                self.assertIn(
                    "vps_platform_last_collection_timestamp_seconds 1793771234\n",
                    output.read_text(),
                )
                first = output.read_bytes()
                with patch("time.time", return_value=1793771294):
                    self.assertEqual(output.read_bytes(), first)
                    module.main()
                self.assertIn(
                    "vps_platform_last_collection_timestamp_seconds 1793771294\n",
                    output.read_text(),
                )
                registry.write_text("{")
                with patch("time.time", return_value=1793771354):
                    module.main()
                self.assertIn("vps_platform_collect_success 0\n", output.read_text())
                self.assertIn(
                    "vps_platform_last_collection_timestamp_seconds 1793771354\n",
                    output.read_text(),
                )

    def test_platform_metrics_exclude_retired_compute_but_keep_disk_and_no_secrets(self):
        path = COLLECTION / "roles/observability/files/platform-metrics.py"
        self.assertTrue(path.exists(), "platform metrics exporter is not implemented")
        spec = importlib.util.spec_from_file_location("platform_metrics", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "protocol": 1,
                        "instances": {
                            "alpha-prod": {
                                "application": "alpha",
                                "environment": "prod",
                                "status": "ready",
                                "budget": {"memory_mib": 512},
                                "storage_budget_gib": 2,
                            },
                            "alpha-staging": {
                                "application": "alpha",
                                "environment": "staging",
                                "status": "retired",
                                "budget": {"memory_mib": 512},
                                "storage_budget_gib": 3,
                                "secret": "private-value",
                            },
                        },
                    }
                )
            )
            output = module.render_metrics(registry, root / "reboot-required")
            self.assertIn("vps_platform_reserved_memory_mib 512\n", output)
            self.assertIn("vps_platform_storage_budget_gib 5\n", output)
            self.assertIn(
                'vps_platform_instances{application="alpha",environment="staging",status="retired"} 1',
                output,
            )
            self.assertIn("node_reboot_required 0\n", output)
            self.assertNotIn("private-value", output)
            (root / "reboot-required").touch()
            self.assertIn(
                "node_reboot_required 1\n",
                module.render_metrics(registry, root / "reboot-required"),
            )
            data = json.loads(registry.read_text())
            for invalid in [-1, float("nan"), float("inf")]:
                data["instances"]["alpha-prod"]["budget"]["memory_mib"] = invalid
                registry.write_text(json.dumps(data))
                self.assertIn(
                    "vps_platform_collect_success 0\n",
                    module.render_metrics(registry, root / "reboot-required"),
                )
            registry.write_text("{")
            self.assertIn(
                "vps_platform_collect_success 0\n",
                module.render_metrics(registry, root / "reboot-required"),
            )
