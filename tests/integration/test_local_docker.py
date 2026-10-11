"""Opt-in: VPS_INTEGRATION=1 runs the real controller against the local Docker daemon.

Only resources of the vpsitest-* instances below are created, inspected and removed.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import helpers  # noqa: E402, F401  (puts the controller package on sys.path)
from vps_platform.controller import Controller  # noqa: E402
from vps_platform.runtime import Runtime  # noqa: E402

ENABLED = os.environ.get("VPS_INTEGRATION") == "1"
DOCKER = shutil.which("docker")
BUSYBOX = (
    "docker.io/library/busybox:1.37.0"
    "@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e"
)
POSTGRES = (
    "docker.io/library/postgres:17.6-alpine"
    "@sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94"
)
APPLICATIONS = ("vpsitest-a", "vpsitest-b", "vpsitest-c")
INSTANCES = ("vpsitest-a-pr-1", "vpsitest-b-pr-2", "vpsitest-c-pr-3")
RESOURCE_KINDS = ("container", "network", "volume")
PASSWORD = "integration-only-password-not-a-secret"
SEED_SQL = (
    "CREATE TABLE IF NOT EXISTS fixtures (marker text); "
    "INSERT INTO fixtures SELECT '$MARKER' WHERE NOT EXISTS (SELECT 1 FROM fixtures);"
)


def docker(*args):
    completed = subprocess.run([DOCKER, *args], capture_output=True, text=True, timeout=120)
    if completed.returncode:
        raise AssertionError(f"docker {args[0]} failed: {completed.stderr[-2000:]}")
    return completed.stdout.strip()


def local_runner(argv, **kwargs):
    """The controller pins /usr/bin/docker and a root environment: map them to this machine."""
    if argv[0] != "/usr/bin/docker":
        raise AssertionError("the integration runtime only runs docker")
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT")
        if key in os.environ
    }
    return subprocess.run([DOCKER, *argv[1:]], **{**kwargs, "env": environment})


class LocalRuntime(Runtime):
    def free_memory_mib(self):
        return int(docker("info", "--format", "{{.MemTotal}}")) / 1048576


def instance_resources(instance):
    label = "label=vps.platform.instance=" + instance
    return {
        kind: docker(kind, "ls", "-q", "--filter", label, *container_flags(kind)).split()
        for kind in RESOURCE_KINDS
    }


def container_flags(kind):
    if kind == "container":
        return ["--all"]
    return []


def remove_test_resources():
    for instance in INSTANCES:
        resources = instance_resources(instance)
        for identifier in resources["container"]:
            docker("container", "rm", "--force", identifier)
        for kind in ("network", "volume"):
            for identifier in resources[kind]:
                docker(kind, "rm", identifier)


def delivery(application, pull_request, generation, release):
    return {
        "protocol": 1,
        "operation": "apply",
        "application": application,
        "environment": "preview",
        "pull_request": pull_request,
        "generation": generation,
        "compose": {
            "services": services(f"{application}-pr-{pull_request}", release),
            "volumes": {"data": {}},
        },
        "routes": [],
        "storage_budget_gib": 1,
    }


def services(marker, release):
    return {
        "db": {
            "image": POSTGRES,
            "user": "70:70",
            "cpus": 0.2,
            "mem_limit": "384m",
            "memswap_limit": "384m",
            "pids_limit": 128,
            "environment": {
                "POSTGRES_USER": "app",
                "POSTGRES_DB": "app",
                "POSTGRES_PASSWORD": PASSWORD,
            },
            "volumes": ["data:/var/lib/postgresql/data"],
            "healthcheck": {
                "test": ["CMD", "pg_isready", "--host", "127.0.0.1", "--username", "app"],
                "interval": "3s",
                "timeout": "3s",
                "start_period": "60s",
                "retries": 10,
            },
        },
        "seed": {
            "image": POSTGRES,
            "x-vps-init": True,
            "user": "70:70",
            "cpus": 0.1,
            "mem_limit": "128m",
            "pids_limit": 64,
            "environment": {"PGPASSWORD": PASSWORD, "MARKER": marker},
            "command": ["sh", "-c", f'psql -h db -U app -d app -v ON_ERROR_STOP=1 -c "{SEED_SQL}"'],
            "depends_on": {"db": {"condition": "service_healthy"}},
        },
        "web": {
            "image": BUSYBOX,
            "cpus": 0.1,
            "mem_limit": "64m",
            "pids_limit": 32,
            "environment": {"RELEASE": release},
            "command": [
                "sh",
                "-c",
                "mkdir -p /tmp/www && echo ok > /tmp/www/index.html"
                " && exec httpd -f -p 3000 -h /tmp/www",
            ],
            "healthcheck": {
                "test": ["CMD", "wget", "-q", "--spider", "http://127.0.0.1:3000/"],
                "interval": "2s",
                "timeout": "2s",
                "retries": 10,
            },
            "depends_on": {
                "db": {"condition": "service_healthy"},
                "seed": {"condition": "service_completed_successfully"},
            },
        },
    }


def database(instance, sql):
    return docker("exec", f"vps-{instance}-db-1", "psql", "-U", "app", "-d", "app", "-tAc", sql)


def fixtures(instance):
    return database(instance, "SELECT string_agg(marker, ',' ORDER BY marker) FROM fixtures")


@unittest.skipUnless(ENABLED and DOCKER, "set VPS_INTEGRATION=1 with a local Docker daemon")
class LocalDockerTests(unittest.TestCase):
    def setUp(self):
        for instance in INSTANCES:
            leftovers = [item for items in instance_resources(instance).values() for item in items]
            self.assertEqual(
                leftovers, [], f"{instance} resources already exist; not touching them"
            )
        self.addCleanup(remove_test_resources)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        config = {
            "accounts": {
                application + "-ci": {"application": application, "environments": ["preview"]}
                for application in APPLICATIONS
            },
            "administrators": ["operator"],
            "domain": "",
            "apps_dir": str(self.root / "apps"),
            "minimum_free_disk_gib": 1,
            "image_growth_reserve_gib": 1,
            "disk_warning_gib": 2,
        }
        self.controller = Controller(
            config, self.root / "state", LocalRuntime(config, runner=local_runner)
        )

    def call(self, payload):
        return self.controller.request(payload, payload["application"] + "-ci")

    def test_previews_are_isolated_admitted_updated_and_cleaned(self):
        first = self.call(delivery("vpsitest-a", 1, 1, "1"))
        self.assertEqual(first["status"], "ready", first)
        second = self.call(delivery("vpsitest-b", 2, 1, "1"))
        self.assertEqual(second["status"], "ready", second)

        third = self.call(delivery("vpsitest-c", 3, 1, "1"))
        self.assertEqual(third["status"], "refused")
        self.assertEqual(
            [item["instance"] for item in third["occupants"]],
            ["vpsitest-a-pr-1", "vpsitest-b-pr-2"],
        )
        self.assertEqual(instance_resources("vpsitest-c-pr-3"), dict.fromkeys(RESOURCE_KINDS, []))

        self.assertEqual(fixtures("vpsitest-a-pr-1"), "vpsitest-a-pr-1")
        self.assertEqual(fixtures("vpsitest-b-pr-2"), "vpsitest-b-pr-2")
        database("vpsitest-a-pr-1", "INSERT INTO fixtures VALUES ('changed-in-a')")
        self.assertEqual(fixtures("vpsitest-b-pr-2"), "vpsitest-b-pr-2")

        web = json.loads(docker("inspect", "vps-vpsitest-a-pr-1-web-1"))[0]["HostConfig"]
        self.assertEqual(
            (web["NanoCpus"], web["Memory"], web["MemorySwap"], web["PidsLimit"]),
            (100000000, 64 * 1048576, 64 * 1048576, 32),
        )
        self.assertEqual((web["CapDrop"], web["PortBindings"]), (["ALL"], {}))

        update = self.call(delivery("vpsitest-a", 1, 2, "2"))
        self.assertEqual(update["status"], "ready", update)
        self.assertEqual(fixtures("vpsitest-a-pr-1"), "changed-in-a,vpsitest-a-pr-1")
        environment = docker(
            "inspect", "--format", "{{json .Config.Env}}", "vps-vpsitest-a-pr-1-web-1"
        )
        self.assertIn("RELEASE=2", json.loads(environment))

        destroy = self.controller.request(
            {
                "protocol": 1,
                "operation": "destroy",
                "application": "vpsitest-a",
                "environment": "preview",
                "pull_request": 1,
                "generation": 3,
            },
            "vpsitest-a-ci",
        )
        self.assertEqual(destroy["status"], "destroyed", destroy)
        self.assertEqual(instance_resources("vpsitest-a-pr-1"), dict.fromkeys(RESOURCE_KINDS, []))
        self.assertEqual(fixtures("vpsitest-b-pr-2"), "vpsitest-b-pr-2")
        plan = {**delivery("vpsitest-c", 3, 1, "1"), "operation": "plan"}
        self.assertEqual(self.call(plan)["status"], "planned")

        registry = self.root / "state/registry.json"
        state = json.loads(registry.read_text())
        state["instances"]["vpsitest-b-pr-2"]["expires_at"] = 1
        registry.write_text(json.dumps(state))
        cleanup = self.controller.cleanup("operator")
        self.assertEqual(cleanup["status"], "cleaned", cleanup)
        self.assertEqual(instance_resources("vpsitest-b-pr-2"), dict.fromkeys(RESOURCE_KINDS, []))
