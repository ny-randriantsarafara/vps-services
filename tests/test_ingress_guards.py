import tempfile
import unittest
from pathlib import Path

from helpers import policy, request
from vps_platform.compose import normalize
from vps_platform.policy import Policy, Refused
from vps_platform.runtime import Runtime, caddy_configuration


class GuardTests(unittest.TestCase):
    def settings(self):
        data = policy(Path("/tmp"))
        data.update(
            domain="example.com",
            instance_hostnames={"alpha-pr-1": ["home-assistant.example.com"]},
            onboarding_guards={
                "home-assistant.example.com": {"path": "/api/onboarding", "step": "user"}
            },
        )
        return data

    def test_alias_owned_only_by_exact_instance(self):
        p = Policy(self.settings())
        payload = request()
        payload["routes"] = [
            {"hostname": "home-assistant.example.com", "service": "web", "port": 8123}
        ]
        self.assertEqual(
            normalize(payload, p, "alpha-pr-1", {})[2][0]["hostname"], "home-assistant.example.com"
        )
        with self.assertRaises(Refused):
            normalize(payload, p, "beta-pr-1", {})
        runtime = Runtime(p)
        self.assertEqual(
            len(runtime._own_routes("alpha-pr-1", normalize(payload, p, "alpha-pr-1", {})[2])), 1
        )

    def test_alias_cannot_steal_namespace(self):
        for hostname in [
            "beta.example.com",
            "api.beta.example.com",
            "beta-pr-2.example.com",
            "bad..example.com",
        ]:
            data = self.settings()
            data["instance_hostnames"]["alpha-pr-1"] = [hostname]
            with self.assertRaises(Refused):
                Policy(data)

    def test_guard_requires_owned_hostname_and_strict_schema(self):
        for guard in [
            {"path": "https://evil/", "step": "user"},
            {"path": "/api/onboarding", "step": "user", "open": True},
        ]:
            data = self.settings()
            data["onboarding_guards"]["home-assistant.example.com"] = guard
            with self.assertRaises(Refused):
                Policy(data)
        data = self.settings()
        data["onboarding_guards"]["evil.example.com"] = {"path": "/api/onboarding", "step": "user"}
        with self.assertRaises(Refused):
            Policy(data)

    def test_static_guard_and_permanent_shield(self):
        route = {"hostname": "home-assistant.example.com", "upstream": "127.0.0.1:20000"}
        for opened in [True, False]:
            config = caddy_configuration("/run/caddy.sock", [route], {route["hostname"]: opened})
            routes = config["apps"]["http"]["servers"]["platform"]["routes"]
            self.assertEqual(routes[0]["match"][0]["path"], ["/api/onboarding/users*"])
            self.assertEqual(routes[0]["handle"][0]["status_code"], 403)
            self.assertEqual(
                routes[1]["handle"][0]["handler"], "reverse_proxy" if opened else "static_response"
            )

    def test_stop_grace_boundaries(self):
        for value in ["0s", "301s", "1ms", True, 10]:
            payload = request()
            payload["compose"]["services"]["web"]["stop_grace_period"] = value
            with self.assertRaises(Refused):
                normalize(payload, Policy(policy(Path("/tmp"))), "alpha-pr-1", {})
        payload["compose"]["services"]["web"]["stop_grace_period"] = "120s"
        self.assertEqual(
            normalize(payload, Policy(policy(Path("/tmp"))), "alpha-pr-1", {})[0]["services"][
                "web"
            ]["stop_grace_period"],
            "120s",
        )

    def test_fail_closed_guard_responses(self):
        from unittest.mock import MagicMock, patch

        route = {"hostname": "home-assistant.example.com", "upstream": "127.0.0.1:20000"}
        runtime = Runtime(Policy(self.settings()))
        for body, expected in [
            (b"[]", False),
            (b"{}", False),
            (b"bad", False),
            (b'[{"step":"user","done":1}]', False),
            (b'[{"step":"user","done":true},{"step":"user","done":true}]', False),
            (b'[{"step":"user","done":true}]', True),
            (b"x" * 65537, False),
        ]:
            connection = MagicMock()
            result = connection.getresponse.return_value
            result.status = 200
            result.read1.side_effect = [body, b""]
            with patch("vps_platform.runtime.http.client.HTTPConnection", return_value=connection):
                self.assertEqual(runtime._guard_open(route), expected)
        with patch("vps_platform.runtime.http.client.HTTPConnection") as connection:
            connection.return_value.request.side_effect = OSError("unreachable")
            self.assertFalse(runtime._guard_open(route))
        self.assertEqual(runtime._public_status([route]), "protected")

    def test_completed_onboarding_opens_guard(self):
        from unittest.mock import MagicMock, patch

        route = {"hostname": "home-assistant.example.com", "upstream": "127.0.0.1:20000"}
        runtime = Runtime(Policy(self.settings()))
        # Home Assistant stops serving the onboarding API once every step is done.
        for status, body, expected in [
            (404, b"404: Not Found", True),
            (404, b"404: Not Found\n", False),
            (404, b"", False),
            (404, b'[{"step":"user","done":true}]', False),
            (500, b"404: Not Found", False),
            (401, b"404: Not Found", False),
        ]:
            connection = MagicMock()
            result = connection.getresponse.return_value
            result.status = status
            result.read1.side_effect = [body, b""]
            with patch("vps_platform.runtime.http.client.HTTPConnection", return_value=connection):
                self.assertEqual(runtime._guard_open(route), expected, (status, body))

    def test_app_cannot_submit_guard(self):
        from helpers import BoundaryRuntime
        from vps_platform.controller import Controller

        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            controller = Controller(policy(root), root / "state", BoundaryRuntime(root))
            payload = request()
            payload["onboarding_guards"] = {}
            self.assertEqual(controller.request(payload, "alpha-ci")["status"], "refused")
            self.assertEqual(controller.refresh_ingress("alpha-ci")["status"], "refused")

    def test_refresh_preserves_generation_and_runtime(self):
        from helpers import BoundaryRuntime
        from vps_platform.controller import Controller

        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            runtime = BoundaryRuntime(root)
            runtime.refresh_ingress = lambda routes: {}
            controller = Controller(policy(root), root / "state", runtime)
            self.assertEqual(controller.request(request(), "alpha-ci")["status"], "ready")
            before = controller.registry.load()
            resources = runtime.inventory()
            self.assertEqual(controller.refresh_ingress("admin")["status"], "ready")
            self.assertEqual(controller.registry.load(), before)
            self.assertEqual(runtime.inventory(), resources)

    def test_duplicate_alias_and_other_namespace_rejected(self):
        data = self.settings()
        data["instance_hostnames"]["beta-pr-1"] = ["home-assistant.example.com"]
        with self.assertRaises(Refused):
            Policy(data)

    def test_no_reload_for_unchanged_config(self):
        from unittest.mock import MagicMock

        from vps_platform.state import replace_json

        with tempfile.TemporaryDirectory() as root:
            data = policy(Path(root))
            data["domain"] = "example.com"
            data["caddy_config"] = str(Path(root) / "caddy.json")
            runtime = Runtime(data, runner=MagicMock(), caddy_loader=MagicMock())
            replace_json(
                Path(data["caddy_config"]),
                caddy_configuration(runtime.policy["caddy_admin_socket"], []),
                0o644,
            )
            runtime.refresh_ingress([])
            runtime.runner.assert_not_called()
            runtime.caddy_loader.assert_not_called()

    def test_runtime_stop_timeout_must_match(self):
        from vps_platform.runtime import RuntimeFailure, require_admitted_limits

        service = {"cpus": 0.2, "mem_limit": "384m", "pids_limit": 64, "stop_grace_period": "120s"}
        host = {
            "NanoCpus": 200000000,
            "Memory": 384 * 1048576,
            "MemorySwap": 384 * 1048576,
            "PidsLimit": 64,
            "StopTimeout": 10,
        }
        with self.assertRaises(RuntimeFailure):
            require_admitted_limits(host, service)
        host["StopTimeout"] = 120
        require_admitted_limits(host, service)

    def test_existing_route_cannot_be_stolen(self):
        payload = request()
        payload["routes"] = [
            {"hostname": "home-assistant.example.com", "service": "web", "port": 8123}
        ]
        existing = {
            "retired-prod": {
                "routes": [
                    {
                        "hostname": "home-assistant.example.com",
                        "service": "web",
                        "port": 8123,
                        "upstream": "127.0.0.1:20000",
                    }
                ]
            }
        }
        with self.assertRaises(Refused):
            normalize(payload, Policy(self.settings()), "alpha-pr-1", existing)

    def test_slow_headers_have_total_deadline(self):
        self.assert_slow_response_bounded(
            b"HTTP/1.1 200 OK\r\nX-Slow: ",
            b'\r\nContent-Length: 29\r\n\r\n[{"step":"user","done":true}]',
        )

    def test_slow_chunk_framing_has_total_deadline(self):
        self.assert_slow_response_bounded(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n1;ext=",
            b"\r\nx\r\n0\r\n\r\n",
        )

    def assert_slow_response_bounded(self, preamble, ending):
        import socket
        import threading
        import time
        from unittest.mock import patch

        from vps_platform import runtime as runtime_module

        client, server = socket.socketpair()
        stopped = threading.Event()

        def drip():
            try:
                server.recv(4096)
                server.sendall(preamble)
                for _ in range(20):
                    if stopped.wait(0.025):
                        return
                    server.sendall(b"a")
                server.sendall(ending)
            except OSError:
                pass
            finally:
                server.close()

        original_timers = {t for t in threading.enumerate() if isinstance(t, threading.Timer)}
        sender = threading.Thread(target=drip)
        sender.start()

        def connect(connection):
            connection.sock = client
            client.settimeout(connection.timeout)

        runtime = Runtime(Policy(self.settings()))
        route = {"hostname": "home-assistant.example.com", "upstream": "127.0.0.1:20000"}
        try:
            with (
                patch.object(runtime_module, "ONBOARDING_TIMEOUT_SECONDS", 0.15, create=True),
                patch.object(runtime_module.http.client.HTTPConnection, "connect", connect),
            ):
                started = time.monotonic()
                self.assertFalse(runtime._guard_open(route))
                self.assertLess(time.monotonic() - started, 0.3)
        finally:
            stopped.set()
            client.close()
            sender.join(1)
            self.assertFalse(sender.is_alive())
            self.assertEqual(
                {t for t in threading.enumerate() if isinstance(t, threading.Timer)},
                original_timers,
            )
