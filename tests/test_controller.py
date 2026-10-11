import fcntl
import json
import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path

from helpers import BoundaryRuntime, policy, request
from vps_platform.policy import Refused

try:
    from vps_platform.controller import Controller
except ImportError:
    Controller = None


def concurrent_apply(root, app, pr, queue):
    root = Path(root)
    result = Controller(policy(root), root / "state", BoundaryRuntime(root)).request(
        request(app, pr), app + "-ci"
    )
    queue.put(result["status"])


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.assertIsNotNone(Controller, "controller behavior is not implemented")
        self.runtime = BoundaryRuntime(self.root)
        self.controller = Controller(policy(self.root), self.root / "state", self.runtime)

    def call(self, payload=None, actor="alpha-ci"):
        return self.controller.request(payload or request(), actor)

    def test_the_runtime_rechecks_the_disk_for_the_declared_storage_budget(self):
        payload = {**request(), "storage_budget_gib": 3}
        self.assertEqual(self.call(payload)["status"], "ready")
        self.assertEqual(self.runtime.storage_budgets, [3])

    def test_third_preview_is_refused_without_eviction(self):
        self.assertEqual(self.call()["status"], "ready")
        self.assertEqual(self.call(request("beta", 2), "beta-ci")["status"], "ready")
        self.assertEqual(self.call(request("gamma", 3), "gamma-ci")["status"], "refused")
        self.assertEqual(set(self.runtime.inventory()), {"alpha-pr-1", "beta-pr-2"})

    def test_third_preview_refusal_names_the_occupants_and_their_expiry(self):
        self.call()
        self.call(request("beta", 2), "beta-ci")
        refused = self.call(request("gamma", 3), "gamma-ci")
        occupants = refused["occupants"]
        self.assertEqual([item["instance"] for item in occupants], ["alpha-pr-1", "beta-pr-2"])
        self.assertTrue(all(item["status"] == "ready" for item in occupants))
        self.assertTrue(all(item["expires_at"] > time.time() for item in occupants))

    def test_a_memory_increase_must_leave_the_free_memory_margin(self):
        self.runtime.available_memory_mib = 384 + 511
        refused = self.call()
        self.assertEqual(
            (refused["status"], refused["reason"]),
            ("refused", "available memory margin prevents admission"),
        )
        self.runtime.available_memory_mib = 384 + 512
        self.assertEqual(self.call()["status"], "ready")
        self.runtime.available_memory_mib = 0
        self.assertEqual(self.call(request(generation=2))["status"], "ready")

    def test_waiting_for_the_controller_lock_is_bounded(self):
        config = policy(self.root)
        config["lock_timeout_seconds"] = 1
        controller = Controller(config, self.root / "state", self.runtime)
        (self.root / "state").mkdir(mode=0o700)
        holder = os.open(self.root / "state/controller.lock", os.O_CREAT | os.O_RDWR, 0o600)
        self.addCleanup(os.close, holder)
        fcntl.flock(holder, fcntl.LOCK_EX)
        started = time.monotonic()
        result = controller.request(request(), "alpha-ci")
        self.assertGreaterEqual(time.monotonic() - started, 1)
        self.assertEqual(
            (result["status"], result["reason"]),
            ("refused", "another operation holds the controller lock; retry later"),
        )
        self.assertEqual(self.runtime.inventory(), {})

    def test_every_request_is_audited_without_secret_values(self):
        self.call()
        self.call(request("beta", 2), "beta-ci")
        self.call(request("gamma", 3), "gamma-ci")
        audit = self.root / "state/audit.jsonl"
        entries = [json.loads(line) for line in audit.read_text().splitlines()]
        self.assertEqual(audit.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("private-", audit.read_text())
        first, _, refused = entries
        self.assertEqual(
            {key: first[key] for key in ("actor", "operation", "instance", "generation", "status")},
            {
                "actor": "alpha-ci",
                "operation": "apply",
                "instance": "alpha-pr-1",
                "generation": 1,
                "status": "ready",
            },
        )
        self.assertEqual(first["images"], {"web": "example/web@sha256:" + "a" * 64})
        self.assertEqual(
            (refused["actor"], refused["status"], refused["reason"]),
            ("gamma-ci", "refused", "global preview limit reached; no existing preview is evicted"),
        )

    def test_expired_preview_destruction_is_audited_with_the_operator(self):
        self.call()
        state_path = self.root / "state/registry.json"
        state = json.loads(state_path.read_text())
        state["instances"]["alpha-pr-1"]["expires_at"] = 1
        state_path.write_text(json.dumps(state))
        self.controller.cleanup("admin")
        last = json.loads((self.root / "state/audit.jsonl").read_text().splitlines()[-1])
        self.assertEqual(
            (last["actor"], last["operation"], last["instance"], last["status"]),
            ("admin", "cleanup", "alpha-pr-1", "destroyed"),
        )

    def test_global_lock_protects_admission_across_processes(self):
        ctx = multiprocessing.get_context("fork")
        queue = ctx.Queue()
        processes = [
            ctx.Process(target=concurrent_apply, args=(str(self.root), app, index, queue))
            for index, app in enumerate(("alpha", "beta", "gamma"), 1)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(5)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(
            sorted(queue.get(timeout=1) for _ in processes), ["ready", "ready", "refused"]
        )
        self.assertEqual(len(self.runtime.inventory()), 2)

    def test_same_pr_update_and_idempotence_preserve_data(self):
        self.call()
        directory = self.root / "apps/alpha/pr-1"
        marker = directory / "data-test"
        marker.write_text("retained")
        self.assertFalse(self.call()["changed"])
        result = self.call(request(generation=2))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(marker.read_text(), "retained")
        self.assertEqual(len(self.runtime.inventory()), 1)
        self.assertEqual(self.call(request(generation=1))["status"], "refused")
        altered = request(generation=2)
        altered["compose"]["services"]["web"]["cpus"] = 0.1
        self.assertEqual(self.call(altered)["status"], "refused")

    def test_actor_is_checked_for_prod_and_other_app(self):
        payload = request("beta")
        self.assertEqual(self.call(payload)["status"], "refused")
        payload = request()
        payload["environment"] = "prod"
        del payload["pull_request"]
        self.assertEqual(self.call(payload)["status"], "refused")
        payload["actor"] = "admin"
        self.assertEqual(self.call(payload)["status"], "refused")
        self.assertEqual(self.runtime.inventory(), {})

    def test_application_names_cannot_end_like_an_instance(self):
        for application in ("alpha-prod", "alpha-staging", "alpha-pr-1"):
            with self.subTest(application=application):
                config = policy(self.root)
                config["accounts"] = {"ci": {"application": application, "environments": ["prod"]}}
                with self.assertRaises(Refused):
                    Controller(config, self.root / "state", self.runtime)
                self.assertEqual(self.call(request(application, 1), "admin")["status"], "refused")

    def test_aggregate_budget_and_single_instance_budget(self):
        config = policy(self.root)
        config["preview_limit"] = 4
        self.controller = Controller(config, self.root / "state", self.runtime)
        for app, pr in [("alpha", 1), ("beta", 2)]:
            payload = request(app, pr)
            payload["compose"]["services"]["web"].update(cpus=0.5, mem_limit="1g")
            self.assertEqual(self.call(payload, app + "-ci")["status"], "ready")
        self.assertEqual(self.call(request("gamma", 3), "gamma-ci")["status"], "refused")
        payload = request(pr=4)
        payload["compose"]["services"]["web"]["cpus"] = 0.51
        self.assertEqual(self.call(payload)["status"], "refused")

    def test_secrets_are_private_and_absent_from_state_and_output(self):
        result = self.call()
        state = (self.root / "state/registry.json").read_text()
        compose = self.root / "apps/alpha/pr-1/compose.json"
        self.assertNotIn("private-", state + json.dumps(result))
        self.assertIn("private-$$HOME-$${secret}", compose.read_text())
        self.assertEqual(compose.stat().st_mode & 0o777, 0o600)
        self.assertEqual(compose.parent.stat().st_mode & 0o777, 0o700)

    def test_plan_has_no_files_or_mutations(self):
        result = self.call(request(operation="plan"))
        self.assertEqual(result["status"], "planned")
        self.assertFalse(result["changed"])
        self.assertFalse((self.root / "apps").exists())
        self.assertEqual(self.runtime.inventory(), {})
        self.assertFalse((self.root / "state/registry.json").exists())

    def test_tombstone_blocks_old_and_implicit_reopen(self):
        self.call()
        self.assertEqual(
            self.call(request(operation="destroy", generation=2))["status"], "destroyed"
        )
        self.assertFalse(self.call(request(operation="destroy", generation=2))["changed"])
        self.assertEqual(self.call(request(generation=1))["status"], "refused")
        self.assertEqual(self.call(request(generation=3))["status"], "refused")
        payload = request(generation=3)
        payload["reopen"] = True
        self.assertEqual(self.call(payload)["status"], "ready")

    def test_failed_apply_and_incomplete_cleanup_keep_reservation(self):
        self.runtime.fail_apply = True
        failed = self.call()
        self.assertEqual(failed["status"], "failed")
        self.assertNotIn("private-", json.dumps(failed))
        self.runtime.fail_apply = False
        self.call(request("beta", 2), "beta-ci")
        self.assertEqual(self.call(request("gamma", 3), "gamma-ci")["status"], "refused")
        self.runtime.fail_destroy = True
        self.assertEqual(self.call(request(operation="destroy", generation=2))["status"], "failed")
        self.assertEqual(self.call(request("gamma", 3), "gamma-ci")["status"], "refused")

    def test_unknown_docker_objects_block_admission(self):
        self.runtime.path.write_text(
            json.dumps({"untracked-pr-9": {"owned": True, "resources": ["volume"]}})
        )
        self.assertEqual(self.call()["status"], "refused")
        self.assertEqual(set(self.runtime.inventory()), {"untracked-pr-9"})

    def test_ttl_cleanup_excludes_durable_instances(self):
        self.call()
        payload = request()
        payload["environment"] = "prod"
        del payload["pull_request"]
        self.call(payload, "admin")
        state_path = self.root / "state/registry.json"
        state = json.loads(state_path.read_text())
        for instance in state["instances"].values():
            instance["expires_at"] = 1
        state_path.write_text(json.dumps(state))
        result = self.controller.cleanup("admin")
        self.assertEqual(result["status"], "cleaned")
        self.assertEqual(set(self.runtime.inventory()), {"alpha-prod"})

    def test_lowering_the_preview_limit_keeps_existing_previews(self):
        self.call()
        self.call(request("beta", 2), "beta-ci")
        config = policy(self.root)
        config["preview_limit"] = 1
        self.controller = Controller(config, self.root / "state", self.runtime)
        self.assertEqual(self.call(request(generation=2))["status"], "ready")
        self.assertEqual(self.call(request("gamma", 3), "gamma-ci")["status"], "refused")
        self.assertEqual(set(self.runtime.inventory()), {"alpha-pr-1", "beta-pr-2"})

    def test_crash_while_preparing_is_reclaimed_only_after_its_lease(self):
        self.runtime.crash_apply = True
        with self.assertRaises(SystemExit):
            self.call()
        self.runtime.crash_apply = False
        self.assertEqual(self.controller.cleanup("admin")["changed"], False)
        self.assertEqual(set(self.runtime.inventory()), {"alpha-pr-1"})
        state_path = self.root / "state/registry.json"
        state = json.loads(state_path.read_text())
        state["instances"]["alpha-pr-1"]["lease_until"] = 1
        state_path.write_text(json.dumps(state))
        result = self.controller.cleanup("admin")
        self.assertEqual(result["status"], "cleaned")
        self.assertEqual(self.runtime.inventory(), {})
        self.assertEqual(self.call(request("beta", 2), "beta-ci")["status"], "ready")

    def test_renew_extends_preview_without_changing_secrets(self):
        self.call()
        compose = self.root / "apps/alpha/pr-1/compose.json"
        original = compose.read_bytes()
        result = self.call(request(operation="renew"))
        self.assertEqual(result["status"], "renewed")
        self.assertEqual(compose.read_bytes(), original)

    def test_status_reports_the_registered_state_and_runtime_presence(self):
        absent = self.call(request(operation="status"))
        self.assertEqual((absent["status"], absent["runtime_present"]), ("absent", False))
        self.call()
        present = self.call(request(operation="status"))
        self.assertEqual((present["status"], present["runtime_present"]), ("ready", True))
        self.assertFalse(present["changed"])

    def test_logs_are_bounded_and_carry_a_secret_warning(self):
        logs = request(operation="logs")
        logs["tail"] = 50
        self.assertEqual(self.call(logs)["status"], "refused")
        self.call()
        result = self.call(logs)
        self.assertEqual(result["status"], "logs")
        self.assertEqual(result["logs"], "application log")
        self.assertIn("secrets", result["reason"])
        logs["tail"] = 1001
        self.assertEqual(self.call(logs)["status"], "refused")

    def test_lifecycle_requests_are_refused_with_their_reason(self):
        def renew_staging():
            payload = request(operation="renew")
            payload["environment"] = "staging"
            del payload["pull_request"]
            return payload

        def with_fields(operation, **fields):
            payload = request(operation=operation)
            payload.update(fields)
            return payload

        cases = [
            (with_fields("rollback"), "unsupported operation"),
            (
                with_fields("destroy", routes=[]),
                "deployment fields are not accepted for this operation",
            ),
            (with_fields("destroy", generation=0), "a positive delivery generation is required"),
            (with_fields("apply", reopen="yes"), "invalid reopen flag"),
            (with_fields("apply", storage_budget_gib=0), "finite storage budget is required"),
            (renew_staging(), "only a current healthy preview can be renewed"),
            (request(operation="renew"), "only a current healthy preview can be renewed"),
        ]
        for payload, reason in cases:
            with self.subTest(reason=reason):
                result = self.call(payload)
                self.assertEqual((result["status"], result["reason"]), ("refused", reason))

    def test_durable_instances_are_never_destroyed_by_the_preview_lifecycle(self):
        payload = request()
        payload["environment"] = "staging"
        del payload["pull_request"]
        self.call(payload)
        destroy = request(operation="destroy", generation=2)
        destroy["environment"] = "staging"
        del destroy["pull_request"]
        result = self.call(destroy)
        self.assertEqual(
            (result["status"], result["reason"]),
            ("refused", "durable instances cannot be destroyed through preview lifecycle"),
        )
        self.assertEqual(set(self.runtime.inventory()), {"alpha-staging"})

    def test_administrators_list_previews_and_others_are_refused(self):
        self.call()
        staging = request()
        staging["environment"] = "staging"
        del staging["pull_request"]
        self.call(staging)
        previews = self.controller.status("admin", previews=True)
        self.assertEqual([item["instance"] for item in previews["instances"]], ["alpha-pr-1"])
        everything = self.controller.status("admin")
        self.assertEqual(len(everything["instances"]), 2)
        self.assertEqual(self.controller.status("alpha-ci")["status"], "refused")
        self.assertEqual(self.controller.cleanup("alpha-ci")["status"], "refused")
