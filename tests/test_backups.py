import fcntl
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import BoundaryRuntime, policy, request
from vps_platform.cli import main
from vps_platform.controller import Controller
from vps_platform.policy import Policy, Refused
from vps_platform.runtime import Runtime, RuntimeFailure

TRUE_COMMAND = str(Path("/usr/bin/true").resolve())
FALSE_COMMAND = str(Path("/usr/bin/false").resolve())
SLEEP_COMMAND = str(Path("/usr/bin/sleep").resolve())


class BackupRuntime(BoundaryRuntime):
    def __init__(self, root):
        super().__init__(root)
        self.root = root
        self.fail_backup = False
        self.backup_commands = []

    def backup(self, instance, command):
        self.backup_commands.append(command)
        descriptor = os.open(self.root / "state/controller.lock", os.O_RDWR)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError("backup ran outside the controller lock")
        finally:
            os.close(descriptor)
        if self.fail_backup:
            raise RuntimeError("private-backup-provider-secret")
        state = json.loads((self.root / "state/registry.json").read_text())
        record = state["instances"][instance]
        compose = self.root / "apps" / record["application"] / record["suffix"] / "compose.json"
        (self.root / "snapshot.json").write_bytes(compose.read_bytes())


class BackupControllerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = policy(self.root)
        self.command = ["/usr/bin/true", "--config", "/etc/alpha/backup.json"]
        self.data["backup_commands"] = {"alpha-pr-1": self.command}
        self.runtime = BackupRuntime(self.root)
        try:
            self.controller = Controller(self.data, self.root / "state", self.runtime)
        except Refused as error:
            self.fail(f"Administrator backup configuration was rejected: {error}")

    def call(self, operation="apply", generation=1, actor="alpha-ci"):
        return self.controller.request(request(operation=operation, generation=generation), actor)

    def test_update_backs_up_previous_data_before_replacing_compose(self):
        self.assertEqual(self.call()["status"], "ready")
        self.assertFalse((self.root / "snapshot.json").exists())
        old = (self.root / "apps/alpha/pr-1/compose.json").read_bytes()
        payload = request(generation=2)
        payload["compose"]["services"]["web"]["environment"]["TOKEN"] = "new-private-value"
        self.assertEqual(self.controller.request(payload, "alpha-ci")["status"], "ready")
        self.assertEqual((self.root / "snapshot.json").read_bytes(), old)
        self.assertNotEqual((self.root / "apps/alpha/pr-1/compose.json").read_bytes(), old)
        self.assertEqual(self.runtime.backup_commands, [self.command])

    def test_failed_backup_preserves_registry_compose_and_runtime(self):
        self.call()
        before = self.controller.registry.load()
        compose = (self.root / "apps/alpha/pr-1/compose.json").read_bytes()
        resources = self.runtime.inventory()
        self.runtime.fail_backup = True
        result = self.call(generation=2)
        self.assertEqual((result["status"], result["changed"]), ("failed", False))
        self.assertEqual(self.controller.registry.load(), before)
        self.assertEqual((self.root / "apps/alpha/pr-1/compose.json").read_bytes(), compose)
        self.assertEqual(self.runtime.inventory(), resources)
        self.assertNotIn("private-backup-provider-secret", json.dumps(result))
        self.assertNotIn(
            "private-backup-provider-secret", (self.root / "state/audit.jsonl").read_text()
        )

    def test_plan_status_and_repeated_generation_never_back_up(self):
        self.call()
        self.assertEqual(self.call()["status"], "ready")
        self.assertEqual(self.call("plan", 2)["status"], "planned")
        self.assertEqual(self.call("status")["status"], "ready")
        self.assertFalse((self.root / "snapshot.json").exists())
        self.assertEqual(self.runtime.backup_commands, [])

    def test_backup_request_authorizes_exact_existing_instance(self):
        self.call()
        before = self.controller.registry.load()
        for actor in ("beta-ci", "unknown"):
            self.assertEqual(self.call("backup", actor=actor)["status"], "refused")
        self.assertEqual(
            self.controller.request(request(pr=2, operation="backup"), "alpha-ci")["status"],
            "refused",
        )
        result = self.call("backup")
        self.assertEqual((result["status"], result["changed"]), ("backed_up", True))
        self.assertTrue((self.root / "snapshot.json").exists())
        self.assertEqual(self.controller.registry.load(), before)
        payload = request(operation="backup")
        payload["backup_commands"] = {"alpha-pr-1": ["/usr/bin/false"]}
        self.assertEqual(self.controller.request(payload, "alpha-ci")["status"], "refused")

    def test_backup_requires_configured_command_and_healthy_owned_instance(self):
        self.call()
        state = self.controller.registry.load()
        state["instances"]["alpha-pr-1"]["status"] = "failed"
        self.controller.registry.save(state)
        self.assertEqual(self.call("backup")["status"], "refused")
        state["instances"]["alpha-pr-1"]["status"] = "ready"
        self.controller.registry.save(state)
        self.controller.policy.data["backup_commands"] = {}
        self.assertEqual(self.call("backup")["status"], "refused")

    def test_admin_cli_runs_durable_backup_but_deploy_account_cannot_use_admin_cli(self):
        self.data["backup_commands"] = {"alpha-prod": self.command}
        controller = Controller(self.data, self.root / "state", self.runtime)
        payload = request()
        payload["environment"] = "prod"
        del payload["pull_request"]
        self.assertEqual(controller.request(payload, "admin")["status"], "ready")
        for actor, expected in (("alpha-ci", "refused"), ("admin", "backed_up")):
            output = io.StringIO()
            code = main(
                ["backups", "run", "--instance", "alpha-prod"],
                controller=controller,
                actor=actor,
                stdout=output,
            )
            self.assertEqual(json.loads(output.getvalue())["status"], expected)
            self.assertEqual(code, 2 if expected == "refused" else 0)


class BackupRuntimeTests(unittest.TestCase):
    def test_fixed_root_command_runs_but_mismatched_or_user_writable_command_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = policy(root)
            data["backup_commands"] = {"alpha-prod": [TRUE_COMMAND]}
            try:
                runtime = Runtime(data)
            except Refused as error:
                self.fail(f"Administrator backup configuration was rejected: {error}")
            runtime.backup("alpha-prod", [TRUE_COMMAND])
            with self.assertRaises(RuntimeFailure):
                runtime.backup("alpha-prod", [FALSE_COMMAND])
            script = root / "untrusted.sh"
            script.write_text("#!/bin/sh\nexit 0\n")
            script.chmod(0o777)
            runtime.policy.data["backup_commands"]["alpha-prod"] = [str(script)]
            with self.assertRaises(RuntimeFailure):
                runtime.backup("alpha-prod", [str(script)])

    def test_failing_and_timed_out_commands_do_not_report_a_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = policy(Path(temporary))
            for command in ([FALSE_COMMAND], [SLEEP_COMMAND, "1"]):
                data["backup_commands"] = {"alpha-prod": command}
                try:
                    runtime = Runtime(data)
                except Refused as error:
                    self.fail(f"Administrator backup configuration was rejected: {error}")
                with (
                    patch("vps_platform.runtime.BACKUP_TIMEOUT_SECONDS", 0.01, create=True),
                    self.assertRaises(RuntimeFailure),
                ):
                    runtime.backup("alpha-prod", command)

    def test_policy_refuses_arbitrary_instance_and_non_literal_argv(self):
        for instance, command in [
            ("alpha", ["/usr/bin/true"]),
            ("alpha-prod", "true"),
            ("alpha-prod", []),
            ("alpha-prod", ["relative-command"]),
            ("alpha-prod", ["/usr/bin/true", None]),
            ("alpha-prod", ["/usr/bin/true", "bad\x00value"]),
        ]:
            with self.subTest(instance=instance, command=command):
                data = policy(Path("/tmp"))
                data["backup_commands"] = {instance: command}
                with self.assertRaises(Refused):
                    Policy(data)
