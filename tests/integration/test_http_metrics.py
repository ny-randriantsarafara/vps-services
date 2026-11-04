"""Pinned Caddy + Alloy, real requests, no published ports or private host mounts."""

import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import COLLECTION  # noqa: E402
from test_alloy import ALLOY_IMAGE  # noqa: E402
from test_ansible_render import ROOT, run_playbook  # noqa: E402
from vps_platform.runtime import caddy_configuration  # noqa: E402

CADDY_IMAGE = "caddy:2.11.7@sha256:36c24ad91a7ff7bc4c87fe22bfa8df3c4b18da0773d73fc12ee2c52b98c0bb7e"

PROMETHEUS_IMAGE = (
    "prom/prometheus@sha256:fa3302279710be2f21a8301ec17a8b4f2301fd829bd113839b3b6b02b6f191a2"
)


def docker(*arguments, check=True):
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, check=check, timeout=60
    )


@unittest.skipUnless(
    os.environ.get("VPS_HTTP_INTEGRATION") == "1", "opt-in local HTTP metrics check"
)
class HttpMetricsIntegrationTests(unittest.TestCase):
    def test_real_status_counts_and_latency_are_private_bounded_and_not_duplicated(self):
        caddy = "vpsitest-http-" + str(os.getpid())
        alloy = "vpsitest-http-alloy-" + str(os.getpid())
        prometheus = "vpsitest-http-prometheus-" + str(os.getpid())
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            route = {
                "hostname": "my-media.apps.example.test",
                "upstream": "127.0.0.1:8081",
                "service": "web",
                "port": 8081,
                "application": "my-media",
                "environment": "prod",
            }
            config = caddy_configuration("/run/admin.sock", [route])
            http = config["apps"]["http"]
            http["servers"]["platform"].update(listen=[":8080"], automatic_https={"disable": True})
            http["servers"]["fixture"] = {
                "listen": [":8081"],
                "routes": [
                    {
                        "match": [{"path": ["/private-" + str(code)]}],
                        "handle": [
                            {
                                "handler": "headers",
                                "response": {"set": {"X-Private": ["synthetic-response-secret"]}},
                            },
                            {"handler": "static_response", "status_code": code, "body": "fixture"},
                        ],
                        "terminal": True,
                    }
                    for code in [200, 500, 503]
                ],
            }
            for log in config["logging"]["logs"].values():
                if "writer" in log:
                    log["writer"]["filename"] = "/test/vps-http.json"
            (folder / "config.json").write_text(json.dumps(config))
            run_playbook(
                str(ROOT / "tests/playbooks/render-observability.yml"),
                "-e",
                f"observability_output={folder}",
            )
            rendered = (folder / "config.alloy").read_text()
            source = rendered[rendered.index('loki.source.file "http_traffic"') :]
            source = source.replace("/var/log/caddy/vps-http.json", "/test/vps-http.json")
            source = source.replace('scrape_interval = "60s"', 'scrape_interval = "250ms"')
            source = source.replace(
                "prometheus.remote_write.cloud.receiver", "prometheus.remote_write.fixture.receiver"
            )
            source += """
prometheus.remote_write "fixture" {
  external_labels = { host = "personal-vps" }
  endpoint {
    url = "http://127.0.0.1:9090/api/v1/write"
    queue_config { batch_send_deadline = "250ms" }
  }
}
prometheus.exporter.unix "bridge_fixture" {
  set_collectors = ["textfile"]
  textfile { directory = "/test/bridge" }
}
prometheus.scrape "bridge_fixture" {
  targets = prometheus.exporter.unix.bridge_fixture.targets
  scrape_interval = "250ms"
  forward_to = [prometheus.remote_write.fixture.receiver]
}
"""
            source = source.replace(
                'scrape_interval = "250ms"', 'scrape_timeout = "200ms"\n  scrape_interval = "250ms"'
            )
            traffic_config = 'logging { level = "warn" }\n' + source
            (folder / "traffic.alloy").write_text(traffic_config)
            (folder / "prometheus.json").write_text(json.dumps({"scrape_configs": []}))
            (folder / "registry.json").write_text(json.dumps({"protocol": 1, "instances": {}}))
            (folder / "bridge").mkdir()
            bridge = runpy.run_path(
                str(COLLECTION / "roles/observability/files/platform-metrics.py")
            )
            bridge_output = bridge["render_metrics"](folder / "registry.json", folder / "reboot")
            (folder / "bridge/platform.prom").write_text(bridge_output)
            expected_bridge = float(
                next(
                    line.split()[1]
                    for line in bridge_output.splitlines()
                    if line.startswith("vps_platform_last_collection_timestamp_seconds ")
                )
            )

            def local_metrics():
                return docker(
                    "exec", caddy, "wget", "-qO-", "http://127.0.0.1:12345/metrics"
                ).stdout

            def exported(name, code=None, expected=None):
                for _ in range(50):
                    response = docker(
                        "exec",
                        caddy,
                        "wget",
                        "-qO-",
                        "http://127.0.0.1:9090/api/v1/query?query=" + name,
                    )
                    samples = json.loads(response.stdout)["data"]["result"]
                    samples = [
                        sample
                        for sample in samples
                        if code is None or sample["metric"].get("code") == code
                    ]
                    if len(samples) == 1 and (
                        expected is None or abs(float(samples[0]["value"][1]) - expected) < 0.00001
                    ):
                        return samples[0]
                    time.sleep(0.1)
                self.fail("Expected exported metric absent/mismatched: " + name + str(samples))

            try:
                docker(
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "-v",
                    f"{folder}:/test",
                    CADDY_IMAGE,
                    "caddy",
                    "validate",
                    "--config",
                    "/test/config.json",
                )
                docker(
                    "run",
                    "-d",
                    "--name",
                    caddy,
                    "--network",
                    "none",
                    "-v",
                    f"{folder}:/test",
                    CADDY_IMAGE,
                    "caddy",
                    "run",
                    "--config",
                    "/test/config.json",
                )
                for _ in range(30):
                    probe = docker(
                        "exec",
                        caddy,
                        "wget",
                        "-qO-",
                        "http://127.0.0.1:8081/private-200",
                        check=False,
                    )
                    if probe.returncode == 0:
                        break
                    time.sleep(0.1)
                else:
                    self.fail(
                        "Caddy fixture did not start: "
                        + probe.stderr
                        + docker("logs", caddy).stderr
                    )
                # A fresh collector must not replay historical traffic from before startup.
                docker(
                    "exec",
                    caddy,
                    "wget",
                    "-qO-",
                    "--header=Host: my-media.apps.example.test",
                    "http://127.0.0.1:8080/private-200",
                    check=False,
                )
                docker(
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    prometheus,
                    "--user",
                    "0:0",
                    "--network",
                    "container:" + caddy,
                    "-v",
                    f"{folder}:/test:ro",
                    PROMETHEUS_IMAGE,
                    "--config.file=/test/prometheus.json",
                    "--storage.tsdb.path=/tmp/prometheus",
                    "--web.listen-address=127.0.0.1:9090",
                    "--web.enable-remote-write-receiver",
                )
                for _ in range(30):
                    ready = docker(
                        "exec", caddy, "wget", "-qO-", "http://127.0.0.1:9090/-/ready", check=False
                    )
                    if ready.returncode == 0:
                        break
                    time.sleep(0.1)
                else:
                    self.fail("Prometheus fixture did not start")

                def start_alloy():
                    docker(
                        "run",
                        "-d",
                        "--name",
                        alloy,
                        "--network",
                        "container:" + caddy,
                        "-v",
                        f"{folder}:/test:ro",
                        ALLOY_IMAGE,
                        "run",
                        "--server.http.listen-addr=127.0.0.1:12345",
                        "--storage.path=/tmp/alloy",
                        "/test/traffic.alloy",
                    )
                    for _ in range(30):
                        ready = docker(
                            "exec",
                            caddy,
                            "wget",
                            "-qO-",
                            "http://127.0.0.1:12345/-/ready",
                            check=False,
                        )
                        if ready.returncode == 0:
                            break
                        time.sleep(0.1)
                    else:
                        self.fail(
                            "Alloy did not start: "
                            + docker("logs", alloy, check=False).stdout
                            + docker("logs", alloy, check=False).stderr
                        )
                    time.sleep(0.2)

                start_alloy()
                for code, count in [(200, 1), (500, 2), (503, 3)]:
                    for _ in range(count):
                        docker(
                            "exec",
                            caddy,
                            "wget",
                            "-qO-",
                            "--header=Host: my-media.apps.example.test",
                            "--header=Authorization: Bearer synthetic-request-secret",
                            "--header=Cookie: session=synthetic-cookie-secret",
                            f"http://127.0.0.1:8080/private-{code}?secret=synthetic-query-secret",
                            check=False,
                        )
                for number in range(10):
                    docker(
                        "exec",
                        caddy,
                        "wget",
                        "-qO-",
                        f"--header=Host: unknown-{number}.test",
                        "http://127.0.0.1:8080/private-503",
                        check=False,
                    )
                records = [
                    json.loads(line) for line in (folder / "vps-http.json").read_text().splitlines()
                ]
                self.assertEqual(len(records), 7)
                self.assertEqual(
                    {
                        str(code): sum(row["status"] == code for row in records)
                        for code in [200, 500, 503]
                    },
                    {"200": 2, "500": 2, "503": 3},
                )
                for row in records:
                    self.assertEqual((row["application"], row["environment"]), ("my-media", "prod"))
                    self.assertGreaterEqual(row["duration"], 0)
                    self.assertNotIn("request", row)
                    self.assertNotIn("resp_headers", row)
                raw = (folder / "vps-http.json").read_text()
                for forbidden in [
                    "synthetic-request-secret",
                    "synthetic-cookie-secret",
                    "synthetic-query-secret",
                    "synthetic-response-secret",
                    "private-503",
                    "127.0.0.1",
                    "my-media.apps.example.test",
                    "unknown-",
                ]:
                    self.assertNotIn(forbidden, raw)
                for _ in range(50):
                    probe = docker(
                        "exec", caddy, "wget", "-qO-", "http://127.0.0.1:12345/metrics", check=False
                    )
                    if "vps_http_requests_total" in probe.stdout:
                        break
                    time.sleep(0.1)
                else:
                    self.fail("Alloy traffic counters absent: " + docker("logs", alloy).stdout)
                lines = [line for line in probe.stdout.splitlines() if line.startswith("vps_http_")]
                for code, count in [("200", 1), ("500", 2), ("503", 3)]:
                    for name in [
                        "vps_http_requests_total",
                        "vps_http_request_duration_seconds_count",
                    ]:
                        samples = [
                            line
                            for line in lines
                            if line.startswith(name + "{") and f'code="{code}"' in line
                        ]
                        self.assertEqual(len(samples), 1, samples)
                        self.assertEqual(float(samples[0].rsplit(" ", 1)[1]), count, samples)
                for code in (500, 503):
                    expected = max(row["ts"] for row in records if row["status"] == code)
                    samples = [
                        line
                        for line in lines
                        if line.startswith("vps_http_last_error_timestamp_seconds{")
                        and f'code="{code}"' in line
                    ]
                    self.assertEqual(len(samples), 1, samples)
                    self.assertAlmostEqual(float(samples[0].rsplit(" ", 1)[1]), expected, places=5)
                self.assertFalse(
                    any(
                        'code="200"' in line
                        for line in lines
                        if line.startswith("vps_http_last_error_timestamp_seconds{")
                    )
                )
                for code in (500, 503):
                    expected = max(row["ts"] for row in records if row["status"] == code)
                    sample = exported("vps_http_last_error_timestamp_seconds", str(code), expected)
                    self.assertEqual(
                        set(sample["metric"]),
                        {"__name__", "host", "application", "environment", "code"},
                    )
                first_bridge = exported(
                    "vps_platform_last_collection_timestamp_seconds", expected=expected_bridge
                )
                # Reset the actual collector, then accelerate only fixture idle retention.
                docker("rm", "-f", alloy)
                (folder / "traffic.alloy").write_text(traffic_config.replace('"24h"', '"3s"'))
                start_alloy()

                def isolated_error():
                    docker(
                        "exec",
                        caddy,
                        "wget",
                        "-qO-",
                        "--header=Host: my-media.apps.example.test",
                        "http://127.0.0.1:8080/private-503",
                        check=False,
                    )
                    expected = json.loads((folder / "vps-http.json").read_text().splitlines()[-1])[
                        "ts"
                    ]
                    exported("vps_http_last_error_timestamp_seconds", "503", expected)
                    count = exported("vps_http_requests_total", "503", 1)
                    self.assertEqual(float(count["value"][1]), 1)
                    return expected

                reset_event = isolated_error()
                for _ in range(80):
                    if not any(
                        line.startswith("vps_http_last_error_timestamp_seconds{")
                        for line in local_metrics().splitlines()
                    ):
                        break
                    time.sleep(0.1)
                else:
                    self.fail("Idle error gauge was not evicted")
                recreated_event = isolated_error()
                self.assertGreater(recreated_event, reset_event)
                second_bridge = exported(
                    "vps_platform_last_collection_timestamp_seconds", expected=expected_bridge
                )
                self.assertGreater(
                    float(second_bridge["value"][0]), float(first_bridge["value"][0])
                )
                self.assertTrue(
                    any(
                        line.startswith("vps_http_request_duration_seconds_bucket{")
                        for line in lines
                    )
                )
                self.assertFalse(
                    any(re.search(r"(?:[,{])(host|method|path|filename)=", line) for line in lines)
                )
            finally:
                docker("rm", "-f", alloy, prometheus, caddy, check=False)


if __name__ == "__main__":
    unittest.main()
