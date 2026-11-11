"""Pinned caddy-l4 binary, controller-generated config, local Docker only."""

import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import FILES  # noqa: E402

sys.path.insert(0, str(FILES))
from vps_platform.runtime import caddy_configuration  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CADDY_BINARY = ROOT / "dist/caddy-2.11.7-l4-0.1.2-linux-amd64"
PYTHON_IMAGE = "python@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df"
CURL_IMAGE = (
    "curlimages/curl@sha256:c1fe1679c34d9784c1b0d1e5f62ac0a79fca01fb6377cdd33e90473c6f9f9a69"
)
DEBIAN_IMAGE = "debian@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc"

RTMP_FIXTURE = """
import os
import socket
import struct
COUNTER = "/tmp/rtmp-connections"
connections = 0
with open(COUNTER, "w") as stream:
    stream.write("0")
listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("0.0.0.0", 1935))
listener.listen(8)
while True:
    conn, _ = listener.accept()
    connections += 1
    with open(COUNTER, "w") as stream:
        stream.write(str(connections))
    try:
        conn.recv(4096)
        s0 = bytes([0x03])
        s1 = struct.pack(">I", 0) + b"\\x00\\x00\\x00\\x00" + bytes(1528)
        conn.sendall(s0 + s1 + bytes(1536))
    finally:
        conn.close()
"""

HTTP_FIXTURE = """
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *_):
        pass
HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
"""


def docker(arguments, check=True, timeout=120):
    return subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


def rtmp_backend_connections(fixture_name):
    for _ in range(20):
        result = docker(["exec", fixture_name, "cat", "/tmp/rtmp-connections"], check=False)
        if result.returncode == 0 and result.stdout.strip().isdigit():
            return int(result.stdout.strip())
        time.sleep(0.1)
    raise AssertionError("RTMP fixture connection counter unavailable")


@unittest.skipUnless(
    os.environ.get("VPS_RTMPS_INTEGRATION") == "1", "opt-in local RTMPS ingress check"
)
class RtmpsIngressIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CADDY_BINARY.is_file():
            subprocess.run([str(ROOT / "scripts/build-caddy.sh")], check=True, timeout=600)

    def test_https_rtmps_neutral_and_plain_tcp(self):
        tag = str(os.getpid())
        network = "vpsitest-rtmps-" + tag
        caddy = "vpsitest-rtmps-caddy-" + tag
        http_fixture = "vpsitest-rtmps-http-" + tag
        rtmp_fixture = "vpsitest-rtmps-rtmp-" + tag
        docker(["network", "create", network])
        try:
            docker(
                [
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    http_fixture,
                    "--network",
                    network,
                    PYTHON_IMAGE,
                    "python",
                    "-c",
                    HTTP_FIXTURE,
                ]
            )
            docker(
                [
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    rtmp_fixture,
                    "--network",
                    network,
                    PYTHON_IMAGE,
                    "python",
                    "-c",
                    RTMP_FIXTURE,
                ]
            )
            routes = [
                {
                    "hostname": "app.example.test",
                    "upstream": http_fixture + ":8080",
                    "application": "fixture",
                    "environment": "prod",
                },
                {
                    "hostname": "ingest.example.test",
                    "upstream": rtmp_fixture + ":1935",
                    "protocol": "rtmps",
                },
            ]
            config = caddy_configuration("/tmp/admin.sock", routes)
            config["apps"]["http"]["servers"]["platform"]["listen"] = [":443"]
            config["apps"]["tls"] = {
                "automation": {"policies": [{"issuers": [{"module": "internal"}]}]},
                "certificates": {
                    "automate": [
                        "app.example.test",
                        "ingest.example.test",
                        "unknown.example.test",
                    ],
                },
            }
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                (folder / "config.json").write_text(json.dumps(config))
                docker(
                    [
                        "run",
                        "-d",
                        "--rm",
                        "--name",
                        caddy,
                        "--platform",
                        "linux/amd64",
                        "--network",
                        network,
                        "-v",
                        f"{folder}:/test:ro",
                        "-v",
                        f"{CADDY_BINARY}:/usr/local/bin/caddy:ro",
                        DEBIAN_IMAGE,
                        "caddy",
                        "run",
                        "--config",
                        "/test/config.json",
                    ]
                )
                caddy_ip = docker(
                    [
                        "inspect",
                        "-f",
                        "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                        caddy,
                    ]
                ).stdout.strip()
                for _ in range(40):
                    probe = docker(
                        [
                            "run",
                            "--rm",
                            "--network",
                            network,
                            CURL_IMAGE,
                            "-kfsS",
                            "--resolve",
                            "app.example.test:443:" + caddy_ip,
                            "https://app.example.test/",
                        ],
                        check=False,
                    )
                    if probe.returncode == 0 and probe.stdout.strip() == "ok":
                        break
                    time.sleep(0.25)
                else:
                    self.fail(
                        "HTTPS route failed: "
                        + probe.stderr
                        + docker(["logs", caddy], check=False).stdout
                    )

                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                tls_ok = False
                for _ in range(40):
                    check = docker(
                        [
                            "run",
                            "--rm",
                            "--network",
                            network,
                            PYTHON_IMAGE,
                            "python",
                            "-c",
                            (
                                "import socket,ssl,sys;"
                                "s=socket.create_connection(('" + caddy_ip + "',443),5);"
                                "t=ssl.create_default_context();"
                                "t.check_hostname=False;t.verify_mode=ssl.CERT_NONE;"
                                "w=t.wrap_socket(s,server_hostname='ingest.example.test');"
                                "w.sendall(bytes([3])+bytes(1536));"
                                "b=w.recv(1);"
                                "sys.stdout.write('ok' if b==b'\\x03' else 'fail')"
                            ),
                        ],
                        check=False,
                    )
                    if check.returncode == 0 and check.stdout.strip() == "ok":
                        tls_ok = True
                        break
                    time.sleep(0.25)
                self.assertTrue(tls_ok, check.stdout + check.stderr)

                unknown = docker(
                    [
                        "run",
                        "--rm",
                        "--network",
                        network,
                        CURL_IMAGE,
                        "-ksS",
                        "-o",
                        "/dev/null",
                        "-w",
                        "%{http_code}",
                        "--resolve",
                        "unknown.example.test:443:" + caddy_ip,
                        "https://unknown.example.test/",
                    ],
                    check=False,
                )
                self.assertEqual(unknown.stdout.strip(), "404")

                backend_before = rtmp_backend_connections(rtmp_fixture)
                plain = docker(
                    [
                        "run",
                        "--rm",
                        "--network",
                        network,
                        PYTHON_IMAGE,
                        "python",
                        "-c",
                        (
                            "import socket,struct,time;"
                            "c0=bytes([3]);"
                            "c1=struct.pack('>I',0)+bytes(1528);"
                            "s=socket.create_connection(('" + caddy_ip + "',443),5);"
                            "s.sendall(c0+c1);"
                            "time.sleep(0.5);"
                            "s.close()"
                        ),
                    ],
                    check=False,
                    timeout=30,
                )
                self.assertEqual(plain.returncode, 0)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if rtmp_backend_connections(rtmp_fixture) == backend_before:
                        break
                    time.sleep(0.1)
                else:
                    backend_after = rtmp_backend_connections(rtmp_fixture)
                    self.fail(
                        "plain TCP on 443 reached the RTMP backend: "
                        f"{backend_before} -> {backend_after}"
                    )
        finally:
            docker(["rm", "-f", caddy, http_fixture, rtmp_fixture], check=False)
            docker(["network", "rm", network], check=False)


if __name__ == "__main__":
    unittest.main()
