import copy
import unittest
from pathlib import Path

from helpers import policy, request

try:
    from vps_platform.compose import normalize
except ImportError:
    normalize = None
from vps_platform.policy import Policy, Refused


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(normalize, "compose validation is not implemented")
        self.payload = request()
        self.policy = Policy(policy(Path("/tmp/test-vps")))

    def render(self):
        return normalize(self.payload, self.policy, "alpha-pr-1", {})

    def test_unsafe_service_options_are_rejected(self):
        for key, value in {
            "build": ".",
            "privileged": True,
            "ports": ["80:80"],
            "network_mode": "host",
            "pid": "host",
            "devices": ["/dev/sda"],
            "env_file": ".env",
            "container_name": "escape",
            "cap_add": ["SYS_ADMIN"],
            "deploy": {"replicas": 2},
            "extra_hosts": ["host:host-gateway"],
            "labels": {"vps.platform.managed": "1"},
        }.items():
            with self.subTest(key=key):
                self.payload = request()
                self.payload["compose"]["services"]["web"][key] = value
                with self.assertRaises(Refused):
                    self.render()

    def test_floating_images_missing_limits_and_bind_mounts_are_rejected(self):
        for changes in [
            {"image": "example:latest"},
            {"cpus": 0},
            {"mem_limit": "0m"},
            {"pids_limit": -1},
            {"volumes": ["/var/run/docker.sock:/sock"]},
            {"healthcheck": {"disable": True}},
            {"environment": {"TOKEN": ""}, "x-vps-required-environment": ["TOKEN"]},
        ]:
            with self.subTest(changes=changes):
                self.payload = request()
                self.payload["compose"]["services"]["web"].update(changes)
                with self.assertRaises(Refused):
                    self.render()

    def test_named_volumes_networks_and_ports_are_instance_owned(self):
        self.payload["compose"]["services"]["web"]["volumes"] = ["data:/data"]
        self.policy.data["domain"] = "apps.example.net"
        self.payload["routes"] = [
            {"hostname": "alpha-pr-1.apps.example.net", "service": "web", "port": 3000}
        ]
        compose, budget, routes = self.render()
        self.assertEqual(compose["volumes"]["data"]["name"], "vps-alpha-pr-1-data")
        self.assertEqual(compose["networks"]["default"]["name"], "vps-alpha-pr-1")
        self.assertEqual(
            compose["services"]["web"]["ports"],
            [{"target": 3000, "published": "20000", "host_ip": "127.0.0.1", "protocol": "tcp"}],
        )
        self.assertEqual(budget, {"cpus": 0.2, "memory_mib": 384})
        self.assertEqual(routes[0]["upstream"], "127.0.0.1:20000")

    def test_wrong_hostname_and_external_volume_are_rejected(self):
        self.policy.data["domain"] = "apps.example.net"
        self.payload["routes"] = [
            {"hostname": "beta.apps.example.net", "service": "web", "port": 3000}
        ]
        with self.assertRaises(Refused):
            self.render()
        self.payload["routes"] = []
        self.payload["compose"]["volumes"]["data"] = {"external": True}
        with self.assertRaises(Refused):
            self.render()

    def test_init_jobs_are_bounded_and_counted(self):
        seed = copy.deepcopy(self.payload["compose"]["services"]["web"])
        seed["x-vps-init"] = True
        seed.pop("healthcheck")
        self.payload["compose"]["services"]["seed"] = seed
        compose, budget, _ = self.render()
        self.assertEqual(budget, {"cpus": 0.4, "memory_mib": 768})
        self.assertEqual(compose["services"]["seed"]["profiles"], ["vps-init"])

    def test_each_contract_violation_is_refused_with_its_reason(self):
        def web(**changes):
            return lambda compose: compose["services"]["web"].update(changes)

        def add_seed_job(compose):
            seed = copy.deepcopy(compose["services"]["web"])
            seed.pop("healthcheck")
            seed["x-vps-init"] = True
            compose["services"]["seed"] = seed

        def web_waits_for_seed_health(compose):
            add_seed_job(compose)
            compose["services"]["web"]["depends_on"] = {"seed": {"condition": "service_healthy"}}

        def web_and_worker_wait_for_each_other(compose):
            worker = copy.deepcopy(compose["services"]["web"])
            worker["depends_on"] = {"web": {"condition": "service_healthy"}}
            compose["services"]["worker"] = worker
            compose["services"]["web"]["depends_on"] = {"worker": {"condition": "service_healthy"}}

        def only_jobs(compose):
            compose["services"]["web"]["x-vps-init"] = True

        cases = [
            (lambda compose: compose.update(networks={}), "unsupported Compose top-level field"),
            (lambda compose: compose.update(services={}), "invalid Compose services or volumes"),
            (web(memswap_limit="512m"), "memory and swap limits must be equal and finite"),
            (web(environment={"PORT": 3000}), "environment must contain explicit string values"),
            (web(**{"x-vps-init": "yes"}), "invalid initialization job"),
            (web(healthcheck={"test": ["NONE"]}), "invalid healthcheck command"),
            (
                web(healthcheck={"test": ["CMD", "/health"], "retries": 0}),
                "invalid healthcheck retries",
            ),
            (
                web(healthcheck={"test": ["CMD", "/health"], "interval": "2 seconds"}),
                "invalid healthcheck duration",
            ),
            (web(restart="always"), "invalid restart policy"),
            (web(command=42), "invalid container command"),
            (web(read_only="yes"), "invalid readonly flag"),
            (web(user=1000), "invalid service option"),
            (web(volumes="data:/data"), "invalid service volumes"),
            (web(volumes=["data:/data:rw"]), "only named volume mounts are accepted"),
            (web(volumes=["data:relative"]), "invalid volume target"),
            (
                web(volumes=[{"type": "volume", "source": ["data"], "target": "/data"}]),
                "only instance-owned volume mounts are accepted",
            ),
            (web(depends_on=["db"]), "dependencies require explicit health conditions"),
            (web(depends_on={"db": {"condition": "service_healthy"}}), "invalid dependency"),
            (web_waits_for_seed_health, "dependency condition must match job or service"),
            (web_and_worker_wait_for_each_other, "cyclic service dependency"),
            (only_jobs, "at least one long-running service is required"),
        ]
        for mutate, reason in cases:
            with self.subTest(reason=reason):
                self.payload = request()
                mutate(self.payload["compose"])
                with self.assertRaises(Refused) as caught:
                    self.render()
                self.assertEqual(str(caught.exception), reason)

    def test_invalid_routes_are_refused_with_their_reason(self):
        self.policy.data["domain"] = "apps.example.net"
        hostname = "alpha-pr-1.apps.example.net"
        for routes, reason in [
            ({"hostname": hostname}, "invalid routes"),
            (
                [{"hostname": hostname, "service": "web", "port": "3000"}],
                "route must target an HTTP service port",
            ),
            (
                [{"hostname": hostname, "service": ["web"], "port": 3000}],
                "route must target an HTTP service port",
            ),
        ]:
            with self.subTest(reason=reason):
                self.payload["routes"] = routes
                with self.assertRaises(Refused) as caught:
                    self.render()
                self.assertEqual(str(caught.exception), reason)

    def test_loopback_ports_are_kept_on_update_and_never_shared(self):
        self.policy.data.update(domain="apps.example.net", port_start=20000, port_end=20001)
        self.payload["routes"] = [
            {"hostname": "alpha-pr-1.apps.example.net", "service": "web", "port": 3000}
        ]
        existing = {
            "alpha-pr-1": {
                "instance": "alpha-pr-1",
                "routes": [{"service": "web", "port": 3000, "upstream": "127.0.0.1:20001"}],
            },
            "beta-pr-2": {
                "instance": "beta-pr-2",
                "routes": [{"service": "web", "port": 3000, "upstream": "127.0.0.1:20000"}],
            },
        }
        _, _, routes = normalize(self.payload, self.policy, "alpha-pr-1", existing)
        self.assertEqual(routes[0]["upstream"], "127.0.0.1:20001")
        existing.pop("alpha-pr-1")
        existing["gamma-pr-3"] = {
            "instance": "gamma-pr-3",
            "routes": [{"service": "web", "port": 3000, "upstream": "127.0.0.1:20001"}],
        }
        with self.assertRaises(Refused) as caught:
            normalize(self.payload, self.policy, "alpha-pr-1", existing)
        self.assertEqual(str(caught.exception), "no loopback ports are available")

    def test_services_wait_for_healthy_services_and_completed_jobs(self):
        services = self.payload["compose"]["services"]
        database = copy.deepcopy(services["web"])
        seed = copy.deepcopy(services["web"])
        seed.pop("healthcheck")
        seed.update({"x-vps-init": True, "depends_on": {"db": {"condition": "service_healthy"}}})
        services.update(db=database, seed=seed)
        services["web"]["depends_on"] = {
            "db": {"condition": "service_healthy"},
            "seed": {"condition": "service_completed_successfully"},
        }
        compose, budget, _ = self.render()
        self.assertEqual(compose["services"]["web"]["depends_on"], services["web"]["depends_on"])
        self.assertEqual(compose["services"]["seed"]["restart"], "no")
        self.assertEqual(budget, {"cpus": 0.6, "memory_mib": 1152})

    def test_service_logs_are_bounded_and_swap_cannot_be_unlimited(self):
        compose, _, _ = self.render()
        self.assertEqual(
            compose["services"]["web"]["logging"],
            {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
        )
        self.assertEqual(compose["services"]["web"]["memswap_limit"], "384m")
        self.payload["compose"]["services"]["web"]["memswap_limit"] = -1
        with self.assertRaises(Refused):
            self.render()
