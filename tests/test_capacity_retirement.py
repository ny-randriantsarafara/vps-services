import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml
from helpers import BoundaryRuntime, policy, request
from vps_platform.cli import main
from vps_platform.controller import Controller
from vps_platform.policy import Policy, Refused


class CapacityRetirementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        config = policy(self.root)
        config["maximum_total_memory_mib"] = 768
        self.runtime = BoundaryRuntime(self.root)
        self.controller = Controller(config, self.root / "state", self.runtime)

    def deploy(self, app="alpha", environment="prod", generation=1, memory=384):
        payload = request(app, generation=generation)
        payload["environment"] = environment
        if environment != "preview":
            del payload["pull_request"]
        payload["compose"]["services"]["web"]["mem_limit"] = f"{memory}m"
        return self.controller.request(payload, "admin")

    def retire(self, instance, actor="admin"):
        output = io.StringIO()
        main(
            ["retire-staging", "--instance", instance],
            controller=self.controller,
            actor=actor,
            stdout=output,
        )
        return json.loads(output.getvalue())

    def state(self):
        return json.loads((self.root / "state/registry.json").read_text())

    def test_global_limit_spans_environments_and_rejects_without_mutation(self):
        self.assertEqual(self.deploy()["status"], "ready")
        self.assertEqual(self.deploy("beta", "staging")["status"], "ready")
        before = self.state()
        refused = self.deploy("gamma", "preview")
        self.assertEqual(
            (refused["status"], refused["reason"]),
            ("refused", "aggregate host memory budget exceeded"),
        )
        self.assertEqual(self.state(), before)
        self.assertEqual(set(self.runtime.inventory()), {"alpha-prod", "beta-staging"})

    def test_production_inventory_preserves_one_full_preview(self):
        inventory = yaml.safe_load(
            (
                Path(__file__).resolve().parents[1] / "inventories/production/group_vars/all.yml"
            ).read_text()
        )
        config = policy(self.root)
        for key in ("budgets", "preview_instance_budget", "maximum_total_memory_mib"):
            config[key] = inventory[f"vps_{key}"]
        self.controller = Controller(config, self.root / "state", self.runtime)
        production = inventory["vps_budgets"]["prod"]["memory_mib"]
        # Two owned stacks fill the declared production envelope, including the vault.
        self.assertEqual(self.deploy("alpha", memory=production // 2)["status"], "ready")
        self.assertEqual(
            self.deploy("beta", memory=production - production // 2)["status"], "ready"
        )
        preview = self.deploy(
            "gamma", "preview", memory=inventory["vps_preview_instance_budget"]["memory_mib"]
        )
        self.assertEqual(preview["status"], "ready", preview.get("reason"))

    def test_replacement_counts_maximum_old_new_once_and_failed_shrink_keeps_old(self):
        self.assertEqual(self.deploy(memory=512)["status"], "ready")
        self.assertEqual(self.deploy("beta", "staging", memory=256)["status"], "ready")
        self.assertEqual(self.deploy(generation=2, memory=513)["status"], "refused")
        self.runtime.fail_apply = True
        self.assertEqual(self.deploy(generation=2, memory=384)["status"], "failed")
        self.assertEqual(self.state()["instances"]["alpha-prod"]["budget"]["memory_mib"], 512)
        self.runtime.fail_apply = False
        self.assertEqual(self.deploy(generation=3, memory=384)["status"], "ready")
        self.assertEqual(self.deploy("gamma", "preview", memory=128)["status"], "ready")

    def test_retirement_retains_private_compose_volumes_and_tracking_and_reuses_capacity(self):
        self.deploy("alpha", "staging")
        self.deploy("beta")
        compose = self.root / "apps/alpha/staging/compose.json"
        previous = compose.read_bytes()
        result = self.retire("alpha-staging")
        self.assertEqual(result["status"], "retired")
        self.assertTrue(result["changed"])
        self.assertEqual(compose.read_bytes(), previous)
        self.assertEqual(compose.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            self.runtime.inventory()["alpha-staging"]["resources"],
            [{"kind": "volume", "id": "retained-data"}],
        )
        record = self.state()["instances"]["alpha-staging"]
        self.assertEqual(record["status"], "retired")
        self.assertEqual(record["storage_budget_gib"], 2)
        self.assertFalse(self.retire("alpha-staging")["changed"])
        self.assertEqual(self.deploy("gamma", "preview")["status"], "ready")
        self.assertEqual(self.deploy("alpha", "staging", generation=2)["status"], "refused")
        self.assertEqual(self.controller._routes(self.state()), [])

    def test_retirement_refuses_nonadmin_production_preview_absent_and_unsafe_targets(self):
        self.deploy()
        self.deploy("beta", "preview")
        before = self.state()
        for name, actor in [
            ("alpha-prod", "admin"),
            ("beta-pr-1", "admin"),
            ("alpha-staging", "alpha-ci"),
            ("unknown-staging", "admin"),
            ("../alpha-staging", "admin"),
        ]:
            with self.subTest(name=name, actor=actor):
                self.assertEqual(self.retire(name, actor)["status"], "refused")
                self.assertEqual(self.state(), before)

    def test_incomplete_retirement_keeps_reservation_and_can_be_retried(self):
        self.deploy("alpha", "staging")
        self.deploy("beta")
        self.runtime.fail_destroy = True
        result = self.retire("alpha-staging")
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["changed"])
        self.assertEqual(self.deploy("gamma", "preview")["status"], "refused")
        self.assertTrue((self.root / "apps/alpha/staging/compose.json").exists())
        self.runtime.fail_destroy = False
        self.assertEqual(self.retire("alpha-staging")["status"], "retired")
        self.assertEqual(self.deploy("gamma", "preview")["status"], "ready")

    def test_retired_compute_reappearance_blocks_admission_without_losing_tracking(self):
        self.deploy("alpha", "staging")
        self.retire("alpha-staging")
        data = self.runtime.inventory()
        data["alpha-staging"]["resources"].append({"kind": "container", "id": "unexpected"})
        self.runtime.path.write_text(json.dumps(data))
        before = self.state()
        self.assertEqual(self.deploy("beta")["status"], "refused")
        self.assertEqual(self.state(), before)

    def test_other_legacy_underreserved_runtime_also_counts_toward_global_admission(self):
        self.deploy("alpha")
        self.deploy("beta", "staging")
        state = self.state()
        state["instances"]["alpha-prod"]["budget"]["memory_mib"] = 128
        (self.root / "state/registry.json").write_text(json.dumps(state))
        self.assertEqual(self.deploy("gamma", "preview", memory=128)["status"], "refused")
        self.assertEqual(self.state(), state)

    def test_invalid_total_limits_are_refused_before_runtime_work(self):
        for value in [0, -1, True, "6144", float("inf"), float("nan")]:
            with self.subTest(value=value), self.assertRaises(Refused):
                Policy({**policy(self.root), "maximum_total_memory_mib": value})
