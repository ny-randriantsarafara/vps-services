import copy
import json
import tempfile
import unittest
from pathlib import Path

from helpers import policy, request
from test_runtime import DockerBoundary
from vps_platform.compose import memory_mib
from vps_platform.controller import Controller, delivery_fingerprint
from vps_platform.runtime import Runtime, RuntimeFailure
from vps_platform.state import atomic_json


class TransitionDocker(DockerBoundary):
    def __init__(self, state):
        super().__init__({})
        self.state = state
        self.peak = 0
        self.reservations = []
        self.fail_service = None

    def __call__(self, argv, **kwargs):
        if "compose" in argv:
            self.compose = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
        result = super().__call__(argv, **kwargs)
        if "up" in argv:
            service = self.compose["services"][argv[-1]]
            host = self.resources["container"]["container-" + argv[-1]]["HostConfig"]
            host.update(
                Memory=int(memory_mib(service["mem_limit"]) * 1048576),
                MemorySwap=int(memory_mib(service["mem_limit"]) * 1048576),
                NanoCpus=service["cpus"] * 1e9,
            )
            current = (
                sum(item["HostConfig"]["Memory"] for item in self.resources["container"].values())
                / 1048576
            )
            self.peak = max(self.peak, current)
            record = json.loads(self.state.read_text())["instances"]["alpha-pr-1"]
            self.reservations.append((current, record["budget"]["memory_mib"]))
            if argv[-1] == self.fail_service:
                raise RuntimeFailure("synthetic failure after creation")
        return result


class TransitionReservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.docker = TransitionDocker(self.root / "state/registry.json")
        config = policy(self.root)
        config.update(
            maximum_total_memory_mib=2048, preview_instance_budget={"cpus": 1, "memory_mib": 2048}
        )
        self.controller = Controller(
            config,
            self.root / "state",
            Runtime(
                config, runner=self.docker, disk_free_gib=lambda: 100, http_probe=lambda route: True
            ),
        )
        self.controller.runtime.free_memory_mib = lambda: 65536

    def apply(self, services, generation=1):
        payload = request(generation=generation)
        web = payload["compose"]["services"]["web"]
        payload["compose"]["services"] = {
            name: {**copy.deepcopy(web), "mem_limit": f"{memory}m"} for name, memory in services
        }
        return self.controller.request(payload, "alpha-ci")

    def cap(self, amount):
        self.controller.policy.data["maximum_total_memory_mib"] = amount

    def test_rename_is_refused_before_starting_overlap_beyond_global_cap(self):
        self.cap(384)
        self.assertEqual(self.apply([("web", 384)])["status"], "ready")
        before = self.docker.peak
        self.assertEqual(self.apply([("renamed", 384)], 2)["status"], "refused")
        self.assertEqual(self.docker.peak, before)
        self.assertEqual(set(self.docker.resources["container"]), {"container-web"})

    def test_same_shape_update_at_capacity_does_not_double_reserve(self):
        self.cap(1024)
        self.assertEqual(self.apply([("web", 768), ("worker", 256)])["status"], "ready")
        self.assertEqual(self.apply([("web", 768), ("worker", 256)], 2)["status"], "ready")
        self.assertTrue(all(current <= reserved for current, reserved in self.docker.reservations))

    def test_mixed_resizing_reserves_per_service_maxima_before_any_start(self):
        self.cap(1024)
        self.assertEqual(self.apply([("worker", 256), ("web", 768)])["status"], "ready")
        self.assertEqual(self.apply([("worker", 768), ("web", 256)], 2)["status"], "refused")
        self.assertEqual(self.docker.peak, 1024)
        self.cap(1536)
        self.docker.fail_service = "worker"
        self.assertEqual(self.apply([("worker", 768), ("web", 256)], 2)["status"], "failed")
        record = json.loads(self.docker.state.read_text())["instances"]["alpha-pr-1"]
        self.assertEqual(record["budget"]["memory_mib"], 1536)
        self.assertTrue(all(current <= reserved for current, reserved in self.docker.reservations))

    def test_failed_rename_keeps_overlap_and_next_request_counts_failed_remnants(self):
        self.cap(768)
        self.assertEqual(self.apply([("web", 384)])["status"], "ready")
        self.docker.fail_service = "renamed"
        self.assertEqual(self.apply([("renamed", 384)], 2)["status"], "failed")
        state = json.loads(self.docker.state.read_text())
        self.assertEqual(state["instances"]["alpha-pr-1"]["budget"]["memory_mib"], 768)
        self.assertTrue(all(current <= reserved for current, reserved in self.docker.reservations))
        self.docker.fail_service = None
        self.assertEqual(self.apply([("third", 384)], 3)["status"], "refused")
        self.assertEqual(
            set(self.docker.resources["container"]), {"container-web", "container-renamed"}
        )
        self.assertEqual(self.apply([("renamed", 384)], 3)["status"], "ready")

    def test_live_oneoff_init_remnants_add_to_new_job_budget(self):
        self.cap(768)
        self.assertEqual(self.apply([("web", 384)])["status"], "ready")
        job = copy.deepcopy(self.docker.resources["container"]["container-web"])
        job["Name"] = "/vps-alpha-pr-1-seed-run-old"
        job["Id"] = "oneoff-old"
        job["Config"]["Labels"].update(
            {"com.docker.compose.service": "seed", "com.docker.compose.oneoff": "True"}
        )
        self.docker.resources["container"]["oneoff-old"] = job
        payload = request(generation=2)
        seed = copy.deepcopy(payload["compose"]["services"]["web"])
        seed.pop("healthcheck")
        seed["x-vps-init"] = True
        payload["compose"]["services"]["seed"] = seed
        self.assertEqual(self.controller.request(payload, "alpha-ci")["status"], "refused")

    def test_legacy_identical_retry_passes_but_real_request_changes_are_rejected(self):
        self.assertEqual(self.apply([("web", 384)])["status"], "ready")
        state = json.loads(self.docker.state.read_text())
        compose_path = self.root / "apps/alpha/pr-1/compose.json"
        compose = json.loads(compose_path.read_text())
        compose["services"]["web"].pop("cpu_shares")
        record = state["instances"]["alpha-pr-1"]
        record["fingerprint"] = delivery_fingerprint(compose, record["routes"], 2)
        atomic_json(compose_path, compose)
        atomic_json(self.docker.state, state)
        self.assertEqual(self.apply([("web", 384)])["status"], "ready")
        self.assertEqual(self.apply([("web", 385)])["status"], "refused")
        payload = request()
        payload["compose"]["services"]["web"]["environment"]["TOKEN"] = "changed"
        self.assertEqual(self.controller.request(payload, "alpha-ci")["status"], "refused")
        payload = request()
        payload["storage_budget_gib"] = 3
        self.assertEqual(self.controller.request(payload, "alpha-ci")["status"], "refused")
