"""Opt-in official-binary config/log checks; no cloud credentials or Docker host mounts."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_ansible_render import ROOT, run_playbook  # noqa: E402

ALLOY_IMAGE = (
    "grafana/alloy:v1.21.3@sha256:8ab871206bd2d8f89277f53abffee5f452a293980788d52f85fa183a87a505a4"
)


@unittest.skipUnless(os.environ.get("VPS_ALLOY_INTEGRATION") == "1", "opt-in local Alloy check")
class AlloyIntegrationTests(unittest.TestCase):
    def test_official_binary_validates_config_and_filters_synthetic_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            run_playbook(
                str(ROOT / "tests/playbooks/render-observability.yml"),
                "-e",
                f"observability_output={folder}",
            )
            environment = {
                "GRAFANA_CLOUD_METRICS_URL": "https://prometheus-test.grafana.net/api/prom/push",
                "GRAFANA_CLOUD_LOGS_URL": "https://logs-test.grafana.net/loki/api/v1/push",
                "GRAFANA_CLOUD_METRICS_USERNAME": "1",
                "GRAFANA_CLOUD_LOGS_USERNAME": "1",
                "GRAFANA_CLOUD_TOKEN": "synthetic",
            }
            env_flags = [
                flag for key, value in environment.items() for flag in ("-e", f"{key}={value}")
            ]
            base = ["docker", "run", "--rm", "--network", "none", "-v", f"{folder}:/test:ro"]
            result = subprocess.run(
                [*base, *env_flags, ALLOY_IMAGE, "validate", "/test/config.alloy"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rendered = (folder / "config.alloy").read_text()
            start = rendered.index('loki.process "redact" {')
            end = rendered.index('\nloki.write "cloud"', start)
            pipeline = rendered[start:end].replace(
                "[loki.write.cloud.receiver]", "[loki.echo.test.receiver]"
            )
            (folder / "log-test.alloy").write_text(
                """logging { level = "info" }
loki.source.file "synthetic" {
  targets = [{__path__ = "/test/synthetic.log", job = "applications", host = "test"}]
  forward_to = [loki.process.redact.receiver]
}
loki.echo "test" {}
"""
                + pipeline
            )
            (folder / "synthetic.log").write_text(
                "\n".join(
                    [
                        "error password=synthetic-password",
                        "error Authorization: Bearer synthetic-access",
                        "error Cookie: session=synthetic-cookie",
                        "info quiet info message",
                        "warn diagnostic for synthetic.person@example.test",
                        "error " + "x" * 5000,
                        "error safe-diagnostic-marker",
                    ]
                )
                + "\n"
            )
            name = "vpsitest-alloy-" + str(os.getpid())
            process = subprocess.Popen(
                [
                    *base,
                    "--name",
                    name,
                    ALLOY_IMAGE,
                    "run",
                    "--server.http.listen-addr=127.0.0.1:12345",
                    "--storage.path=/tmp/alloy",
                    "/test/log-test.alloy",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                output, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                subprocess.run(
                    ["docker", "stop", "-t", "1", name], check=True, capture_output=True, timeout=15
                )
                output, _ = process.communicate(timeout=15)
            finally:
                if process.poll() is None:
                    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
                    process.communicate(timeout=15)
            self.assertIn("safe-diagnostic-marker", output)
            self.assertIn("[REDACTED_EMAIL]", output)
            for forbidden in [
                "synthetic-password",
                "synthetic-access",
                "synthetic-cookie",
                "quiet info message",
                "synthetic.person@example.test",
                "x" * 5000,
            ]:
                self.assertNotIn(forbidden, output)


if __name__ == "__main__":
    unittest.main()
