"""Docker and Caddy boundary. No shell, global prune, or application daemon API."""

import http.client
import json
import math
import os
import pwd
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from .compose import INIT_PROFILE, LABEL_PREFIX, memory_mib, public_hostname
from .policy import Policy
from .state import replace_json

MEMINFO = Path("/proc/meminfo")
GIB = 1073741824
RESOURCE_KINDS = ("container", "network", "volume")
LIST_FLAGS = {"container": "-aq", "network": "-q", "volume": "-q"}
INSPECT_BATCH = 100
MAX_OUTPUT_BYTES = 2097152
MAX_LOG_BYTES = 262144
INSTANCE = re.compile(r"[a-z][a-z0-9-]{1,63}-(?:prod|staging|pr-[1-9][0-9]*)\Z")
COMMAND_ENVIRONMENT = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
    "DOCKER_CONFIG": "/root/.docker",
    "LANG": "C.UTF-8",
}


class RuntimeFailure(RuntimeError):
    pass


def available_memory_mib(meminfo=MEMINFO):
    try:
        for line in Path(meminfo).read_text().splitlines():
            name, _, value = line.partition(":")
            if name == "MemAvailable":
                return int(value.split()[0]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    raise RuntimeFailure("available memory is unknown")


def caddy_configuration(admin_socket, routes):
    handlers = [
        {
            "match": [{"host": [route["hostname"]]}],
            "handle": [{"handler": "reverse_proxy", "upstreams": [{"dial": route["upstream"]}]}],
            "terminal": True,
        }
        for route in routes
    ]
    neutral = {"handle": [{"handler": "static_response", "status_code": 404}], "terminal": True}
    # Port 80 stays with Caddy's automatic HTTPS: ACME challenges and redirects only.
    return {
        "admin": {"listen": "unix/" + admin_socket},
        "apps": {
            "http": {"servers": {"platform": {"listen": [":443"], "routes": [*handlers, neutral]}}}
        },
    }


def resource_labels(kind, obj):
    if kind == "container":
        return obj.get("Config", {}).get("Labels") or {}
    return obj.get("Labels") or {}


def resource_id(obj):
    # Docker volumes have no Id: their name is their identifier.
    return obj.get("Id", obj.get("Name", "").lstrip("/"))


def resource_owner(kind, obj):
    """Owning instance; an '!ambiguous-' key for platform-looking objects; None when unrelated."""
    labels = resource_labels(kind, obj)
    name = obj.get("Name", "").lstrip("/")
    project = labels.get("com.docker.compose.project", "")
    marked = labels.get(LABEL_PREFIX + "managed") == "1"
    if not marked and not name.startswith("vps-") and not project.startswith("vps-"):
        return None
    instance = labels.get(LABEL_PREFIX + "instance")
    if marked and is_owned_by(instance, name, project):
        return instance
    return "!ambiguous-" + kind + "-" + name


def is_owned_by(instance, name, project):
    if not isinstance(instance, str) or not INSTANCE.fullmatch(instance):
        return False
    prefix = "vps-" + instance
    named = name == prefix or name.startswith(prefix + "-")
    return named and project in ("", prefix)


def start_order(services):
    """Dependencies first; Compose validation has already refused cycles."""
    ordered = []

    def visit(name):
        if name in ordered:
            return
        for dependency in services[name].get("depends_on", {}):
            visit(dependency)
        ordered.append(name)

    for name in services:
        visit(name)
    return ordered


def is_init_job(service):
    return INIT_PROFILE in service.get("profiles", [])


def require_admitted_limits(host, service):
    expected_memory = int(memory_mib(service["mem_limit"]) * 1048576)
    if (
        not math.isclose(host.get("NanoCpus", 0), service["cpus"] * 1e9, abs_tol=1)
        or host.get("Memory") != expected_memory
        or host.get("MemorySwap") != expected_memory
        or host.get("PidsLimit") != service["pids_limit"]
    ):
        raise RuntimeFailure("effective resource limits do not match admission")


def is_instance_volume_bind(bind, instance):
    """Compose reports named volume mounts as `volume:target:mode` binds."""
    return bind.startswith("vps-" + instance + "-")


def require_isolation(host, instance):
    if (
        host.get("Privileged")
        or host.get("CapAdd")
        or "ALL" not in host.get("CapDrop", [])
        or not any(value.startswith("no-new-privileges") for value in host.get("SecurityOpt", []))
        or not all(is_instance_volume_bind(bind, instance) for bind in host.get("Binds") or [])
        or host.get("NetworkMode") != "vps-" + instance
        or host.get("PidMode")
        or host.get("IpcMode") == "host"
    ):
        raise RuntimeFailure("effective isolation does not match admission")


def require_loopback_ports(host, service):
    expected = {
        f"{port['target']}/tcp": [{"HostIp": "127.0.0.1", "HostPort": port["published"]}]
        for port in service.get("ports", [])
    }
    if (host.get("PortBindings") or {}) != expected:
        raise RuntimeFailure("effective ports do not match loopback allocation")


def require_instance_mounts(container, instance):
    for mount in container.get("Mounts", []):
        if mount["Type"] != "volume" or not mount.get("Name", "").startswith(
            "vps-" + instance + "-"
        ):
            raise RuntimeFailure("effective mount is outside instance ownership")


def require_healthy(container):
    state = container.get("State", {})
    if state.get("Status") != "running" or state.get("Health", {}).get("Status") != "healthy":
        raise RuntimeFailure("service is not healthy")


def read_previous_configuration(path):
    if not path.exists():
        return None
    return json.loads(path.read_text())


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=10)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class Runtime:
    def __init__(
        self,
        policy,
        runner=subprocess.run,
        caddy_loader=None,
        http_probe=None,
        public_probe=None,
        disk_free_gib=None,
    ):
        self.policy = policy if isinstance(policy, Policy) else Policy(policy)
        self.runner = runner
        self.caddy_loader = caddy_loader or self._caddy_load
        self.http_probe = http_probe or self._loopback_probe
        self.public_probe = public_probe or self._public_probe
        self.disk_free_gib = disk_free_gib or self._disk_free_gib

    def free_memory_mib(self):
        return available_memory_mib()

    def inventory(self):
        result = {}
        try:
            for kind in RESOURCE_KINDS:
                for obj in self._inspect_all(kind):
                    owner = resource_owner(kind, obj)
                    if owner is None:
                        continue
                    entry = result.setdefault(
                        owner, {"owned": not owner.startswith("!ambiguous-"), "resources": []}
                    )
                    entry["resources"].append({"kind": kind, "id": resource_id(obj), "object": obj})
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RuntimeFailure("runtime inventory is malformed") from None
        return result

    def apply(self, instance, compose_path, routes, storage_budget_gib):
        try:
            compose = json.loads(Path(compose_path).read_text())
            self._owned(instance)
            self._pull(instance, compose_path, storage_budget_gib)
            for name in start_order(compose["services"]):
                self._start(instance, compose_path, name, compose["services"][name])
            resources = self._owned(instance)
            self._verify_effective(instance, compose, resources)
            self._remove_retired_containers(resources, compose["services"])
            own_routes = self._own_routes(instance, routes)
            if not all(self.http_probe(route) for route in own_routes):
                raise RuntimeFailure("loopback HTTP readiness failed")
            self._publish(routes)
            return {"local_health": "ready", "http_status": self._public_status(own_routes)}
        except RuntimeFailure:
            raise
        except Exception:
            raise RuntimeFailure("deployment failed; private inspection required") from None

    def destroy(self, instance, compose_path, routes):
        resources = self._owned(instance)
        self._publish(routes)  # Withdraw routes before deleting any data.
        for kind in RESOURCE_KINDS:
            for resource in resources:
                if resource["kind"] == kind:
                    self._remove_if_still_owned(instance, resource)
        if self._owned(instance):
            raise RuntimeFailure("instance resources remain after deletion")

    def logs(self, instance, tail):
        containers = [
            resource for resource in self._owned(instance) if resource["kind"] == "container"
        ]
        sections = [
            self._docker(
                "logs", "--tail", str(tail), resource["id"], timeout=30, max_output=MAX_LOG_BYTES
            )
            for resource in containers
        ]
        return "\n".join(sections)[:MAX_LOG_BYTES]

    def _disk_free_gib(self):
        return shutil.disk_usage(self.policy["apps_dir"]).free / GIB

    def _run(self, argv, timeout=180, max_output=MAX_OUTPUT_BYTES):
        # Files bound memory usage and are unlinked immediately, even on timeout.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            try:
                completed = self.runner(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=errors,
                    timeout=timeout,
                    check=False,
                    env=COMMAND_ENVIRONMENT,
                    cwd="/",
                )
                if completed.returncode:
                    raise RuntimeFailure("host command failed")
                output.seek(0)
                data = output.read(max_output + 1)
                if len(data) > max_output:
                    raise RuntimeFailure("host command output exceeded limit")
                return data.decode("utf-8")
            except (OSError, subprocess.SubprocessError, UnicodeError):
                raise RuntimeFailure("host command unavailable or timed out") from None

    def _docker(self, *args, **kwargs):
        return self._run(["/usr/bin/docker", *args], **kwargs)

    def _inspect_all(self, kind):
        identifiers = self._docker(kind, "ls", LIST_FLAGS[kind], timeout=30).split()
        objects = []
        for start in range(0, len(identifiers), INSPECT_BATCH):
            batch = identifiers[start : start + INSPECT_BATCH]
            objects.extend(json.loads(self._docker(kind, "inspect", *batch, timeout=30)))
        return objects

    def _owned(self, instance):
        inventory = self.inventory()
        if any(not record["owned"] for record in inventory.values()):
            raise RuntimeFailure("ambiguous platform resource ownership")
        return inventory.get(instance, {"owned": True, "resources": []})["resources"]

    def _compose(self, instance, path, *args, timeout=180):
        """Services may wait for init jobs: Compose refuses the project without their profile."""
        return self._docker(
            "compose",
            "--project-name",
            "vps-" + instance,
            "--file",
            str(path),
            "--profile",
            INIT_PROFILE,
            *args,
            timeout=timeout,
        )

    def _pull(self, instance, compose_path, storage_budget_gib):
        """The instance's initial data must still fit above the reserve once its images are in."""
        self._compose(instance, compose_path, "pull", "--quiet", timeout=300)
        if self.disk_free_gib() < self.policy["minimum_free_disk_gib"] + storage_budget_gib:
            raise RuntimeFailure("free disk fell below the reserve after image pull")

    def _start(self, instance, compose_path, name, service):
        if is_init_job(service):
            self._compose(
                instance,
                compose_path,
                "run",
                "--rm",
                "--no-deps",
                "--no-TTY",
                name,
                timeout=300,
            )
            return
        self._compose(
            instance,
            compose_path,
            "up",
            "--detach",
            "--no-deps",
            "--wait",
            "--wait-timeout",
            "120",
            name,
        )

    def _verify_effective(self, instance, compose, resources):
        containers = [
            resource["object"] for resource in resources if resource["kind"] == "container"
        ]
        for name, service in compose["services"].items():
            if is_init_job(service):
                continue
            replicas = [
                container
                for container in containers
                if container["Config"]["Labels"].get("com.docker.compose.service") == name
            ]
            if len(replicas) != 1:
                raise RuntimeFailure("service replica count is not one")
            container = replicas[0]
            require_admitted_limits(container["HostConfig"], service)
            require_isolation(container["HostConfig"], instance)
            require_loopback_ports(container["HostConfig"], service)
            require_instance_mounts(container, instance)
            require_healthy(container)

    def _remove_retired_containers(self, resources, services):
        for resource in resources:
            if resource["kind"] != "container":
                continue
            service = resource["object"]["Config"]["Labels"].get("com.docker.compose.service")
            if service not in services:
                self._docker("container", "rm", "--force", resource["id"])

    def _remove_if_still_owned(self, instance, resource):
        # Re-inspect immediately before deletion; names/labels cannot be trusted from an old scan.
        still_owned = any(
            item["kind"] == resource["kind"] and item["id"] == resource["id"]
            for item in self._owned(instance)
        )
        if not still_owned:
            return
        if resource["kind"] == "container":
            self._docker("container", "rm", "--force", resource["id"], timeout=60)
            return
        self._docker(resource["kind"], "rm", resource["id"], timeout=60)

    def _own_routes(self, instance, routes):
        hostname = public_hostname(instance, self.policy["domain"])
        return [route for route in routes if route["hostname"] == hostname]

    def _public_status(self, own_routes):
        if not own_routes:
            return "unconfigured"
        if all(self.public_probe(route) for route in own_routes):
            return "ready"
        return "unreachable"

    def _publish(self, routes):
        if not self.policy["domain"] and not routes:
            return
        config = caddy_configuration(self.policy["caddy_admin_socket"], routes)
        path = Path(self.policy["caddy_config"])
        if path.parent.is_symlink() or not path.parent.is_dir():
            raise RuntimeFailure("Caddy configuration directory is missing")
        fd, temporary = tempfile.mkstemp(prefix=".caddy-", suffix=".json", dir=path.parent)
        os.close(fd)
        candidate = Path(temporary)
        previous = read_previous_configuration(path)
        try:
            replace_json(candidate, config, 0o600)
            self._run(["/usr/bin/caddy", "validate", "--config", str(candidate)], timeout=30)
            self.caddy_loader(config)  # Caddy /load switches its configuration atomically.
            self._persist_configuration(path, config, previous)
        finally:
            candidate.unlink(missing_ok=True)

    def _persist_configuration(self, path, config, previous):
        try:
            # The caddy service user reads this file again when it restarts.
            replace_json(path, config, 0o644)
        except Exception:
            if previous is not None:
                self.caddy_loader(previous)
            raise

    def _caddy_load(self, config):
        path = self.policy["caddy_admin_socket"]
        try:
            self._require_private_admin_socket(path)
            self._post_configuration(path, config)
        except (OSError, KeyError, http.client.HTTPException):
            raise RuntimeFailure("Caddy administration is unavailable") from None

    def _require_private_admin_socket(self, path):
        info = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISSOCK(info.st_mode)
            or info.st_mode & 0o007
            or info.st_uid not in (0, pwd.getpwnam("caddy").pw_uid)
        ):
            raise RuntimeFailure("Caddy admin socket ownership is unsafe")

    def _post_configuration(self, path, config):
        connection = UnixConnection(path)
        try:
            connection.request(
                "POST", "/load", json.dumps(config).encode(), {"Content-Type": "application/json"}
            )
            result = connection.getresponse()
            if result.status != 200:
                raise RuntimeFailure("Caddy configuration load failed")
            result.read(65536)
        finally:
            connection.close()

    def _loopback_probe(self, route):
        request = urllib.request.Request(
            "http://" + route["upstream"] + "/", headers={"Host": route["hostname"]}
        )
        return self._probe(request)

    def _public_probe(self, route):
        # Normal certificate verification: public reachability includes DNS and TLS.
        return self._probe(urllib.request.Request("https://" + route["hostname"] + "/"))

    def _probe(self, request):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=10) as result:
                return result.status < 500
        except urllib.error.HTTPError as error:
            return 400 <= error.code < 500
        except (OSError, urllib.error.URLError):
            return False
