import json
import sys
import unittest

import yaml
from helpers import COLLECTION, request

sys.path.insert(0, str(COLLECTION / "plugins/modules"))
import deploy_instance  # noqa: E402
from vps_platform import controller  # noqa: E402


class FakeVpsctl:
    """Stands in for `sudo -n /usr/local/sbin/vpsctl request`, the only privileged boundary."""

    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.sent = []

    def __call__(self, data):
        self.sent.append(json.loads(data))
        return self.returncode, self.stdout, ""


def answer(status, changed=False, **diagnostics):
    return json.dumps(
        {
            "changed": changed,
            "instance": "alpha-pr-1",
            "status": status,
            "reason": "controller reason",
            **diagnostics,
        }
    )


def params(operation="apply"):
    payload = request(operation="apply")
    return {
        "operation": operation,
        "application": "alpha",
        "environment": "preview",
        "pull_request": 1,
        "generation": 1,
        "compose": payload["compose"],
        "routes": [],
        "storage_budget_gib": 2,
        "reopen": False,
        "tail": None,
    }


class DeployInstanceModuleTests(unittest.TestCase):
    def test_check_mode_requests_plan_instead_of_apply(self):
        vpsctl = FakeVpsctl(answer("planned"))
        result = deploy_instance.run(params(), True, vpsctl)
        self.assertEqual(vpsctl.sent[0]["operation"], "plan")
        self.assertEqual(vpsctl.sent[0]["protocol"], 1)
        self.assertIs(result["changed"], False)
        self.assertNotIn("failed", result)

    def test_apply_sends_the_complete_version_one_request(self):
        vpsctl = FakeVpsctl(answer("ready", True, local_health="ready", http_status="unconfigured"))
        result = deploy_instance.run(params(), False, vpsctl)
        expected = request(operation="apply")
        expected["reopen"] = False
        self.assertEqual(vpsctl.sent, [expected])
        self.assertEqual(
            result,
            {
                "changed": True,
                "instance": "alpha-pr-1",
                "status": "ready",
                "reason": "controller reason",
                "local_health": "ready",
                "http_status": "unconfigured",
            },
        )

    def test_lifecycle_operations_send_no_deployment_fields(self):
        vpsctl = FakeVpsctl(answer("absent"))
        deploy_instance.run(params("status"), False, vpsctl)
        self.assertEqual(
            vpsctl.sent,
            [
                {
                    "protocol": 1,
                    "operation": "status",
                    "application": "alpha",
                    "environment": "preview",
                    "pull_request": 1,
                }
            ],
        )

    def test_refusal_fails_the_task_with_the_controller_reason(self):
        result = deploy_instance.run(params(), False, FakeVpsctl(answer("refused"), returncode=2))
        self.assertIs(result["failed"], True)
        self.assertEqual(result["msg"], "controller reason")

    def test_preview_limit_refusal_shows_who_holds_the_places(self):
        occupants = [{"instance": "beta-pr-2", "status": "ready", "expires_at": 1.5}]
        vpsctl = FakeVpsctl(answer("refused", occupants=occupants), returncode=2)
        result = deploy_instance.run(params(), False, vpsctl)
        self.assertEqual(result["occupants"], occupants)

    def test_the_module_speaks_the_protocol_of_the_controller(self):
        # The module runs on the operator machine and cannot import the host package.
        self.assertEqual(deploy_instance.OPERATIONS, controller.OPERATIONS)
        self.assertEqual(deploy_instance.DEPLOYMENT_OPERATIONS, controller.DEPLOYMENT_OPERATIONS)
        self.assertEqual(set(deploy_instance.DEPLOYMENT_FIELDS), controller.DEPLOYMENT_FIELDS)
        self.assertEqual(deploy_instance.GENERATION_OPERATIONS, controller.GENERATION_OPERATIONS)

    def test_the_app_role_reports_every_public_field_of_the_module(self):
        role_vars = yaml.safe_load((COLLECTION / "roles/app/vars/main.yml").read_text())
        self.assertEqual(
            set(role_vars["app_public_result_fields"]),
            set(deploy_instance.PUBLIC_FIELDS) - {"changed"},
        )

    def test_protocol_errors_fail_instead_of_reporting_success(self):
        for stdout in ("not json", "[]", json.dumps({"changed": False}), ""):
            with self.subTest(stdout=stdout):
                result = deploy_instance.run(params(), False, FakeVpsctl(stdout))
                self.assertIs(result["failed"], True)
                self.assertNotIn(stdout or "<empty>", result["msg"])

    def test_output_keeps_only_public_fields(self):
        vpsctl = FakeVpsctl(answer("ready", compose={"secret": "private-value"}, request="raw"))
        result = deploy_instance.run(params(), False, vpsctl)
        self.assertNotIn("private-value", json.dumps(result))
        self.assertNotIn("request", result)

    def test_check_mode_never_simulates_destruction_or_renewal(self):
        for operation in ("destroy", "renew"):
            with self.subTest(operation=operation):
                vpsctl = FakeVpsctl(answer("destroyed", True))
                result = deploy_instance.run(params(operation), True, vpsctl)
                self.assertEqual(vpsctl.sent, [])
                self.assertEqual((result["changed"], result["status"]), (False, "not_verified"))
