import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import COLLECTION, BoundaryRuntime, policy

sys.path.insert(0, str(COLLECTION / "plugins/modules"))
import deploy_instance  # noqa: E402
from vps_platform.controller import Controller  # noqa: E402
from vps_platform.policy import Policy  # noqa: E402
from vps_platform.runtime import caddy_configuration  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ANSIBLE_PLAYBOOK = Path(sys.executable).parent / "ansible-playbook"
EXAMPLE = ROOT / "examples/application/deploy/ansible"
SYNTHETIC_WEB_IMAGE = "registry.example.test/exemple/web@sha256:" + "1" * 64
SYNTHETIC_PASSWORD = "synthetic-test-password-with-$-and-@"


def run_playbook(*arguments):
    completed = subprocess.run(
        [str(ANSIBLE_PLAYBOOK), *arguments],
        cwd=ROOT,
        env={**os.environ, "ANSIBLE_CONFIG": str(ROOT / "ansible.cfg"), "ANSIBLE_NOCOLOR": "1"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode:
        raise AssertionError(completed.stdout[-4000:] + completed.stderr[-4000:])
    return completed


class ExampleRenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def render(self, environment, pull_request=None):
        output = self.root / f"{environment}-delivery.json"
        identity = ["-e", f"target_environment={environment}"]
        if pull_request is not None:
            identity += ["-e", f"pull_request_number={pull_request}"]
        run_playbook(
            "-i",
            str(EXAMPLE / "inventory.yml"),
            str(EXAMPLE / "deploy.yml"),
            "--tags",
            "render",
            *identity,
            "-e",
            "release_generation=7",
            "-e",
            json.dumps(
                {
                    "exemple_web_image": SYNTHETIC_WEB_IMAGE,
                    "exemple_database_password": SYNTHETIC_PASSWORD,
                    "app_render_output": str(output),
                    "ansible_connection": "local",
                }
            ),
        )
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        return json.loads(output.read_text())

    def plan(self, environment, pull_request, delivery):
        parameters = {
            "operation": "apply",
            "application": "exemple",
            "environment": environment,
            "pull_request": pull_request,
            "generation": 7,
            "reopen": False,
            "tail": None,
            **delivery,
        }
        controller = Controller(
            policy(self.root), self.root / f"state-{environment}", BoundaryRuntime(self.root)
        )
        return controller.request(deploy_instance.build_request(parameters, "plan"), "admin")

    def test_every_example_environment_renders_a_delivery_the_controller_admits(self):
        for environment, pull_request in (("preview", 42), ("staging", None), ("prod", None)):
            with self.subTest(environment=environment):
                delivery = self.render(environment, pull_request)
                result = self.plan(environment, pull_request, delivery)
                self.assertEqual(
                    (result["status"], result["reason"]),
                    ("planned", "admissible now; apply rechecks under lock"),
                )

    def test_only_previews_load_synthetic_fixtures(self):
        services = {
            environment: set(self.render(environment, pull_request)["compose"]["services"])
            for environment, pull_request in (("preview", 42), ("staging", None), ("prod", None))
        }
        self.assertEqual(
            services,
            {"preview": {"web", "db", "seed"}, "staging": {"web", "db"}, "prod": {"web", "db"}},
        )

    def test_secrets_survive_yaml_rendering_without_interpretation(self):
        delivery = self.render("staging")
        services = delivery["compose"]["services"]
        self.assertEqual(services["db"]["environment"]["POSTGRES_PASSWORD"], SYNTHETIC_PASSWORD)
        self.assertIn(
            "synthetic-test-password-with-%24-and-%40@db:5432",
            services["web"]["environment"]["DATABASE_URL"],
        )


class ControllerPolicyRenderTests(unittest.TestCase):
    def test_inventory_accounts_render_a_policy_vpsctl_accepts_without_public_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "policy.json"
            run_playbook(
                str(ROOT / "tests/playbooks/render-policy.yml"), "-e", f"policy_output={output}"
            )
            data = json.loads(output.read_text())
        Policy(data)
        self.assertEqual(
            data["accounts"],
            {
                "exemple-nonprod": {
                    "application": "exemple",
                    "environments": ["staging", "preview"],
                },
                "exemple-prod": {"application": "exemple", "environments": ["prod"]},
            },
        )
        self.assertEqual(data["administrators"], ["vps-admin", "root"])
        self.assertEqual(data["preview_limit"], 2)


class IngressRenderTests(unittest.TestCase):
    def test_initial_caddy_configuration_is_what_vpsctl_publishes_without_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "vps-platform.json"
            run_playbook(
                str(ROOT / "tests/playbooks/render-ingress.yml"), "-e", f"ingress_output={output}"
            )
            initial = json.loads(output.read_text())
        self.assertEqual(initial, caddy_configuration("/run/caddy/admin.sock", []))
