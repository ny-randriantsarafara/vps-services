import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import FILES, policy, request
from vps_platform.compose import normalize
from vps_platform.policy import Policy
from vps_platform.state import atomic_json

try:
    from vps_platform.runtime import Runtime, RuntimeFailure, available_memory_mib
except ImportError:
    Runtime = None
    RuntimeFailure = RuntimeError
    available_memory_mib = None

STORAGE_BUDGET_GIB = 2


class DockerBoundary:
    def __init__(self, compose):
        self.compose = compose
        self.resources = {"container": {}, "network": {}, "volume": {}}
        self.commands = []
        self.bad_limit = False
        self.fail = False
        self.host_overrides = {}
        self.container_overrides = {}

    def __call__(self, argv, **kwargs):
        self.commands.append(argv)
        if self.fail:
            raise subprocess.TimeoutExpired(argv, 1, output="private-token")
        args = argv[1:]
        output = ""
        if args[0] in self.resources:
            kind = args[0]
            if args[1] == "ls":
                output = "\n".join(self.resources[kind])
            elif args[1] == "inspect":
                output = json.dumps([self.resources[kind][key] for key in args[2:]])
            elif args[1] == "rm":
                for key in args[2:]:
                    if not key.startswith("-"):
                        self.resources[kind].pop(key)
        elif args[0] == "logs":
            output = "log of " + args[-1]
        elif args[0] == "compose" and "up" in args:
            name = args[-1]
            service = self.compose["services"][name]
            self.resources["container"]["container-" + name] = {
                "Id": "container-" + name,
                "Name": "/vps-alpha-pr-1-" + name + "-1",
                "Config": {
                    "Labels": {
                        **service["labels"],
                        "com.docker.compose.service": name,
                        "com.docker.compose.project": "vps-alpha-pr-1",
                    }
                },
                "HostConfig": {
                    "NanoCpus": 0 if self.bad_limit else 200000000,
                    "Memory": 402653184,
                    "MemorySwap": 402653184,
                    "PidsLimit": 64,
                    "Privileged": False,
                    "CapAdd": [],
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "Binds": [],
                    "NetworkMode": "vps-alpha-pr-1",
                    "PidMode": "",
                    "IpcMode": "private",
                    "PortBindings": {},
                    **self.host_overrides,
                },
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
                "Mounts": [],
                **self.container_overrides,
            }
            self.resources["network"]["network-id"] = {
                "Id": "network-id",
                "Name": "vps-alpha-pr-1",
                "Labels": self.compose["networks"]["default"]["labels"],
            }
            for config in self.compose["volumes"].values():
                self.resources["volume"][config["name"]] = {
                    "Name": config["name"],
                    "Labels": config["labels"],
                }
        if kwargs.get("stdout"):
            kwargs["stdout"].write(output.encode())
            kwargs["stdout"].flush()
            return subprocess.CompletedProcess(argv, 0)
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Runtime, "Docker/Caddy runtime is not implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "caddy").mkdir()
        (self.root / "caddy").chmod(0o755)
        config = policy(self.root)
        config.update(
            caddy_config=str(self.root / "caddy/config.json"),
            caddy_admin_socket=str(self.root / "admin.sock"),
        )
        self.policy = Policy(config)
        self.compose, _, _ = normalize(request(), self.policy, "alpha-pr-1", {})
        self.path = self.root / "apps/alpha/pr-1/compose.json"
        atomic_json(self.path, self.compose)
        self.docker = DockerBoundary(self.compose)
        self.loads = []
        self.runtime = Runtime(
            self.policy,
            runner=self.docker,
            caddy_loader=self.loads.append,
            http_probe=lambda route: True,
            public_probe=lambda route: True,
            disk_free_gib=lambda: 50,
        )

    def test_real_runtime_lifecycle_uses_effective_limits_and_targeted_deletion(self):
        result = self.runtime.apply("alpha-pr-1", self.path, [], STORAGE_BUDGET_GIB)
        self.assertEqual(result, {"local_health": "ready", "http_status": "unconfigured"})
        self.assertEqual(set(self.runtime.inventory()), {"alpha-pr-1"})
        self.runtime.destroy("alpha-pr-1", self.path, [])
        self.assertEqual(self.runtime.inventory(), {})
        self.assertFalse(any("prune" in command for command in self.docker.commands))

    def test_image_pull_that_exhausts_the_disk_reserve_starts_nothing(self):
        self.runtime.disk_free_gib = lambda: self.policy["minimum_free_disk_gib"] / 2
        with self.assertRaises(RuntimeFailure) as caught:
            self.runtime.apply("alpha-pr-1", self.path, [], STORAGE_BUDGET_GIB)
        self.assertEqual(str(caught.exception), "free disk fell below the reserve after image pull")
        self.assertTrue(any("pull" in command for command in self.docker.commands))
        self.assertFalse(any("up" in command for command in self.docker.commands))

    def test_image_pull_must_leave_room_for_the_instance_data_above_the_reserve(self):
        reserve = self.policy["minimum_free_disk_gib"]
        self.runtime.disk_free_gib = lambda: reserve + STORAGE_BUDGET_GIB - 0.5
        with self.assertRaises(RuntimeFailure) as caught:
            self.runtime.apply("alpha-pr-1", self.path, [], STORAGE_BUDGET_GIB)
        self.assertEqual(str(caught.exception), "free disk fell below the reserve after image pull")
        self.assertFalse(any("up" in command for command in self.docker.commands))
        self.runtime.disk_free_gib = lambda: reserve + STORAGE_BUDGET_GIB
        result = self.runtime.apply("alpha-pr-1", self.path, [], STORAGE_BUDGET_GIB)
        self.assertEqual(result["local_health"], "ready")

    def test_free_memory_is_read_from_the_kernel_available_estimate(self):
        meminfo = self.root / "meminfo"
        meminfo.write_text("MemTotal:  8000000 kB\nMemFree:  100 kB\nMemAvailable:  1048576 kB\n")
        self.assertEqual(available_memory_mib(meminfo), 1024)
        meminfo.write_text("MemTotal:  8000000 kB\n")
        with self.assertRaises(RuntimeFailure):
            available_memory_mib(meminfo)

    def test_init_jobs_run_before_the_services_that_wait_for_them(self):
        payload = request()
        services = payload["compose"]["services"]
        seed = copy.deepcopy(services["web"])
        seed.pop("healthcheck")
        seed.update({"x-vps-init": True, "depends_on": {"db": {"condition": "service_healthy"}}})
        services.update(db=copy.deepcopy(services["web"]), seed=seed)
        services["web"]["depends_on"] = {
            "seed": {"condition": "service_completed_successfully"},
            "db": {"condition": "service_healthy"},
        }
        self.compose, _, _ = normalize(payload, self.policy, "alpha-pr-1", {})
        atomic_json(self.path, self.compose)
        self.docker.compose = self.compose
        self.runtime.apply("alpha-pr-1", self.path, [], STORAGE_BUDGET_GIB)
        steps = [
            (command[command.index("run")] if "run" in command else "up", command[-1])
            for command in self.docker.commands
            if "compose" in command and ("up" in command or "run" in command)
        ]
        self.assertEqual(steps, [("up", "db"), ("run", "seed"), ("up", "web")])
        # Compose refuses a project where a loaded service depends on a service it did not load.
        for command in self.docker.commands:
            if "compose" in command:
                self.assertEqual(command[6:8], ["--profile", "vps-init"], command)

    def test_containers_of_services_retired_from_the_release_are_removed(self):
        self.docker.resources["container"]["container-worker"] = {
            "Id": "container-worker",
            "Name": "/vps-alpha-pr-1-worker-1",
            "Config": {
                "Labels": {
                    **self.compose["services"]["web"]["labels"],
                    "com.docker.compose.service": "worker",
                    "com.docker.compose.project": "vps-alpha-pr-1",
                }
            },
        }
        self.runtime.apply("alpha-pr-1", self.path, [], STORAGE_BUDGET_GIB)
        self.assertNotIn("container-worker", self.docker.resources["container"])
        self.assertIn("container-web", self.docker.resources["container"])

    def test_effective_isolation_mismatches_block_readiness(self):
        cases = [
            ({"Privileged": True}, {}, "effective isolation does not match admission"),
            ({"NetworkMode": "host"}, {}, "effective isolation does not match admission"),
            ({"Binds": ["/etc:/host:rw"]}, {}, "effective isolation does not match admission"),
            (
                {"Binds": ["vps-beta-pr-2-data:/data:rw"]},
                {},
                "effective isolation does not match admission",
            ),
            (
                {"PortBindings": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "80"}]}},
                {},
                "effective ports do not match loopback allocation",
            ),
            (
                {},
                {"Mounts": [{"Type": "bind", "Source": "/var/run/docker.sock"}]},
                "effective mount is outside instance ownership",
            ),
            (
                {},
                {"State": {"Status": "running", "Health": {"Status": "unhealthy"}}},
                "service is not healthy",
            ),
        ]
        for host, container, reason in cases:
            with self.subTest(reason=reason, host=host, container=container):
                self.docker.resources["container"].clear()
                self.docker.host_overrides = host
                self.docker.container_overrides = container
                with self.assertRaises(RuntimeFailure) as caught:
                    self.runtime.apply("alpha-pr-1", self.path, [], STORAGE_BUDGET_GIB)
                self.assertEqual(str(caught.exception), reason)
        self.assertEqual(self.loads, [])

    def test_compose_binds_of_instance_volumes_are_accepted(self):
        self.docker.host_overrides = {"Binds": ["vps-alpha-pr-1-data:/data:rw"]}
        self.docker.container_overrides = {
            "Mounts": [{"Type": "volume", "Name": "vps-alpha-pr-1-data"}]
        }
        result = self.runtime.apply("alpha-pr-1", self.path, [], STORAGE_BUDGET_GIB)
        self.assertEqual(result, {"local_health": "ready", "http_status": "unconfigured"})

    def test_logs_are_read_only_from_the_instance_containers(self):
        self.runtime.apply("alpha-pr-1", self.path, [], STORAGE_BUDGET_GIB)
        self.assertEqual(self.runtime.logs("alpha-pr-1", 50), "log of container-web")
        self.assertIn(
            ["/usr/bin/docker", "logs", "--tail", "50", "container-web"], self.docker.commands
        )
        self.assertEqual(self.runtime.logs("beta-pr-2", 50), "")

    def test_effective_unlimited_container_blocks_readiness(self):
        self.docker.bad_limit = True
        with self.assertRaises(RuntimeFailure):
            self.runtime.apply("alpha-pr-1", self.path, [], STORAGE_BUDGET_GIB)
        self.assertEqual(self.loads, [])

    def test_a_resource_named_for_another_instance_is_ambiguous(self):
        self.docker.resources["volume"]["vps-alpha-pr-10-data"] = {
            "Name": "vps-alpha-pr-10-data",
            "Labels": self.compose["volumes"]["data"]["labels"],
        }
        inventory = self.runtime.inventory()
        self.assertEqual(list(inventory), ["!ambiguous-volume-vps-alpha-pr-10-data"])
        self.assertFalse(inventory["!ambiguous-volume-vps-alpha-pr-10-data"]["owned"])

    def test_unowned_volume_is_not_deleted(self):
        self.docker.resources["volume"]["vps-alpha-pr-1-data"] = {
            "Name": "vps-alpha-pr-1-data",
            "Labels": {},
        }
        with self.assertRaises(RuntimeFailure):
            self.runtime.destroy("alpha-pr-1", self.path, [])
        self.assertIn("vps-alpha-pr-1-data", self.docker.resources["volume"])

    def test_subprocess_failures_are_sanitized(self):
        self.docker.fail = True
        with self.assertRaises(RuntimeFailure) as caught:
            self.runtime.inventory()
        self.assertNotIn("private-token", str(caught.exception))

    def test_routes_publish_only_after_readiness_and_have_neutral_default(self):
        self.policy.data["domain"] = "apps.example.net"
        route = {
            "hostname": "alpha-pr-1.apps.example.net",
            "service": "web",
            "port": 3000,
            "upstream": "127.0.0.1:20000",
        }
        result = self.runtime.apply("alpha-pr-1", self.path, [route], STORAGE_BUDGET_GIB)
        self.assertEqual(result["http_status"], "ready")
        config = self.loads[-1]
        routes = config["apps"]["http"]["servers"]["platform"]["routes"]
        self.assertEqual(routes[0]["match"], [{"host": ["alpha-pr-1.apps.example.net"]}])
        self.assertEqual(routes[-1]["handle"], [{"handler": "static_response", "status_code": 404}])
        self.assertEqual(config["admin"]["listen"], "unix/" + str(self.root / "admin.sock"))

    def test_application_routes_are_never_served_over_plain_http(self):
        self.policy.data["domain"] = "apps.example.net"
        route = {
            "hostname": "alpha-pr-1.apps.example.net",
            "service": "web",
            "port": 3000,
            "upstream": "127.0.0.1:20000",
        }
        self.runtime.apply("alpha-pr-1", self.path, [route], STORAGE_BUDGET_GIB)
        servers = self.loads[-1]["apps"]["http"]["servers"]
        listeners = [address for server in servers.values() for address in server["listen"]]
        self.assertEqual(listeners, [":443"])

    def test_published_caddy_configuration_stays_readable_by_the_caddy_service(self):
        self.policy.data["domain"] = "apps.example.net"
        caddy_directory = self.root / "caddy"
        route = {
            "hostname": "alpha-pr-1.apps.example.net",
            "service": "web",
            "port": 3000,
            "upstream": "127.0.0.1:20000",
        }
        self.runtime.apply("alpha-pr-1", self.path, [route], STORAGE_BUDGET_GIB)
        self.assertEqual(caddy_directory.stat().st_mode & 0o777, 0o755)
        self.assertEqual((caddy_directory / "config.json").stat().st_mode & 0o777, 0o644)
        self.assertEqual(sorted(path.name for path in caddy_directory.iterdir()), ["config.json"])

    def test_unreachable_public_route_is_reported_apart_from_local_health(self):
        self.policy.data["domain"] = "apps.example.net"
        route = {
            "hostname": "alpha-pr-1.apps.example.net",
            "service": "web",
            "port": 3000,
            "upstream": "127.0.0.1:20000",
        }
        self.runtime.public_probe = lambda route: False
        result = self.runtime.apply("alpha-pr-1", self.path, [route], STORAGE_BUDGET_GIB)
        self.assertEqual(result, {"local_health": "ready", "http_status": "unreachable"})
        self.assertEqual(len(self.loads), 1)

    def test_cli_invalid_json_has_one_safe_json_output(self):
        process = subprocess.run(
            [os.sys.executable, "-I", str(FILES / "launcher.py"), "request"],
            input='{"secret":invalid}',
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(process.returncode, 0)
        result = json.loads(process.stdout)
        self.assertEqual(result["status"], "refused")
        self.assertNotIn("secret", process.stdout + process.stderr)

    def test_every_route_of_the_instance_is_probed_before_and_after_publication(self):
        self.policy.data["domain"] = "apps.example.net"
        routes = [
            {
                "hostname": hostname,
                "service": "web",
                "port": 3000,
                "upstream": "127.0.0.1:" + port,
            }
            for hostname, port in [
                ("alpha-pr-1.apps.example.net", "20000"),
                ("cms.alpha-pr-1.apps.example.net", "20001"),
                ("beta-pr-2.apps.example.net", "20002"),
            ]
        ]
        probed = []
        self.runtime.http_probe = lambda route: probed.append(route["hostname"]) or True
        self.runtime.public_probe = lambda route: not route["hostname"].startswith("beta")
        result = self.runtime.apply("alpha-pr-1", self.path, routes, STORAGE_BUDGET_GIB)
        self.assertEqual(probed, ["alpha-pr-1.apps.example.net", "cms.alpha-pr-1.apps.example.net"])
        self.assertEqual(result["http_status"], "ready")
        self.runtime.public_probe = lambda route: not route["hostname"].startswith("cms.")
        result = self.runtime.apply("alpha-pr-1", self.path, routes, STORAGE_BUDGET_GIB)
        self.assertEqual(result["http_status"], "unreachable")

    def test_loopback_http_readiness_failure_never_publishes_routes(self):
        self.policy.data["domain"] = "apps.example.net"
        route = {
            "hostname": "alpha-pr-1.apps.example.net",
            "service": "web",
            "port": 3000,
            "upstream": "127.0.0.1:20000",
        }
        self.runtime.http_probe = lambda route: False
        with self.assertRaises(RuntimeFailure):
            self.runtime.apply("alpha-pr-1", self.path, [route], STORAGE_BUDGET_GIB)
        self.assertEqual(self.loads, [])

    def test_cli_api_status_cleanup_and_path_override_rejection(self):
        from helpers import BoundaryRuntime
        from vps_platform.cli import main
        from vps_platform.controller import Controller

        controller = Controller(self.policy, self.root / "state", BoundaryRuntime(self.root))
        for arguments, expected in [
            (["status"], "status"),
            (["cleanup"], "cleaned"),
            (["previews", "list"], "status"),
            (["--state-dir", "/tmp/escape", "status"], "refused"),
        ]:
            output = io.StringIO()
            main(arguments, controller=controller, actor="admin", stdout=output)
            self.assertEqual(json.loads(output.getvalue())["status"], expected)

    def test_cli_operator_destroys_a_preview_by_instance_name(self):
        from helpers import BoundaryRuntime
        from vps_platform.cli import main
        from vps_platform.controller import Controller

        runtime = BoundaryRuntime(self.root)
        controller = Controller(self.policy, self.root / "state", runtime)
        controller.request(request(), "alpha-ci")
        output = io.StringIO()
        code = main(
            ["previews", "destroy", "--instance", "alpha-pr-1"],
            controller=controller,
            actor="admin",
            stdout=output,
        )
        self.assertEqual((code, json.loads(output.getvalue())["status"]), (0, "destroyed"))
        self.assertEqual(runtime.inventory(), {})
        output = io.StringIO()
        main(
            ["previews", "destroy", "--instance", "alpha-pr-1"],
            controller=controller,
            actor="alpha-ci",
            stdout=output,
        )
        self.assertEqual(json.loads(output.getvalue())["status"], "refused")

    def test_cli_duplicate_oversized_or_nonfinite_json_is_refused(self):
        from vps_platform.cli import main

        for data in ['{"protocol":1,"protocol":1}', '{"protocol":NaN}', " " * 1048577]:
            output = io.StringIO()
            code = main(["request"], stdin=io.StringIO(data), stdout=output)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "refused")
