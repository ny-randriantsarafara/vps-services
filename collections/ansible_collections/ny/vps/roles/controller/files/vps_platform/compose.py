"""Explicit Compose subset: application data cannot add host privileges."""

import copy
import re

from .policy import NAME, Refused, positive_number

IMAGE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._/:+-]*@sha256:[a-f0-9]{64}\Z")
ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
DURATION = re.compile(r"[1-9][0-9]*(?:ms|s|m)\Z")
SERVICE_FIELDS = {
    "image",
    "stop_grace_period",
    "cpus",
    "mem_limit",
    "memswap_limit",
    "pids_limit",
    "environment",
    "healthcheck",
    "command",
    "entrypoint",
    "volumes",
    "depends_on",
    "restart",
    "user",
    "working_dir",
    "read_only",
    "x-vps-init",
    "x-vps-required-environment",
}
PLATFORM_EXTENSIONS = ("x-vps-init", "x-vps-required-environment")
HEALTHCHECK_FIELDS = {"test", "interval", "timeout", "start_period", "retries"}
MOUNT_FIELDS = {"type", "source", "target", "read_only"}
ROUTE_FIELDS = {"hostname", "service", "port"}
ROUTE_PREFIX = re.compile(r"[a-z][a-z0-9]{0,31}\Z")
RESTART_POLICIES = ("no", "on-failure", "unless-stopped")
DEPENDENCY_CONDITIONS = ("service_healthy", "service_completed_successfully")
MAX_SERVICES = 16
MAX_VOLUMES = 16
MAX_ROUTES = 16
MAX_SERVICE_CPUS = 3
MAX_SERVICE_MEMORY_MIB = 6144
MAX_SERVICE_PIDS = 1024
LABEL_PREFIX = "vps.platform."
INIT_PROFILE = "vps-init"
LOGGING = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}


def memory_mib(value):
    if type(value) is int and value > 0:
        return value / (1024 * 1024)
    if isinstance(value, str):
        match = re.fullmatch(r"([1-9][0-9]*)([bkmg])", value.lower())
        if match:
            return int(match[1]) * {"b": 1 / 1048576, "k": 1 / 1024, "m": 1, "g": 1024}[match[2]]
    raise Refused("every service requires a finite memory limit")


def escape(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [escape(item) for item in value]
    if isinstance(value, dict):
        return {key: escape(item) for key, item in value.items()}
    return value


def labels(instance):
    return {LABEL_PREFIX + "managed": "1", LABEL_PREFIX + "instance": instance}


def public_hostname(instance, domain):
    """Production answers on the application name; other instances on their instance name."""
    return instance.removesuffix("-prod") + "." + domain


def is_instance_hostname(hostname, instance, domain):
    """The primary hostname, or one DNS label prepended to it: never another instance's name."""
    if not isinstance(hostname, str) or not domain:
        return False
    primary = public_hostname(instance, domain)
    prefix, _, rest = hostname.partition(".")
    return hostname == primary or (rest == primary and bool(ROUTE_PREFIX.fullmatch(prefix)))


def is_name(value):
    return isinstance(value, str) and bool(NAME.fullmatch(value))


def is_job(service):
    return isinstance(service, dict) and service.get("x-vps-init", False) is True


def upstream_port(route):
    return route["upstream"].rsplit(":", 1)[-1]


def normalize(payload, policy, instance, existing):
    services, volumes = compose_sections(payload.get("compose"))
    for name, service in services.items():
        validate_service(name, service, services, volumes)
    require_acyclic(services)
    if all(is_job(service) for service in services.values()):
        raise Refused("at least one long-running service is required")
    routes = allocate_routes(payload.get("routes", []), policy, instance, existing, services)
    normalized = {
        "name": "vps-" + instance,
        "services": {
            name: runtime_service(name, service, instance, volumes, routes)
            for name, service in services.items()
        },
        "volumes": {
            name: {"name": f"vps-{instance}-{name}", "labels": labels(instance)} for name in volumes
        },
        "networks": {
            "default": {"name": "vps-" + instance, "driver": "bridge", "labels": labels(instance)}
        },
    }
    budget = {
        "cpus": round(sum(service["cpus"] for service in services.values()), 6),
        "memory_mib": sum(memory_mib(service["mem_limit"]) for service in services.values()),
    }
    return normalized, budget, routes


def compose_sections(compose):
    if not isinstance(compose, dict) or set(compose) - {"services", "volumes"}:
        raise Refused("unsupported Compose top-level field")
    services = compose.get("services")
    volumes = compose.get("volumes", {})
    if (
        not isinstance(services, dict)
        or not 1 <= len(services) <= MAX_SERVICES
        or not isinstance(volumes, dict)
        or len(volumes) > MAX_VOLUMES
    ):
        raise Refused("invalid Compose services or volumes")
    if any(not is_name(name) or settings not in ({}, None) for name, settings in volumes.items()):
        raise Refused("only instance-owned named volumes are accepted")
    return services, volumes


def validate_service(name, service, services, volumes):
    if not is_name(name) or not isinstance(service, dict) or set(service) - SERVICE_FIELDS:
        raise Refused("unsupported Compose service field")
    if "stop_grace_period" in service:
        stop_grace_seconds(service["stop_grace_period"])
    validate_limits(service)
    validate_environment(service)
    if type(service.get("x-vps-init", False)) is not bool:
        raise Refused("invalid initialization job")
    validate_healthcheck(service)
    validate_process_options(service)
    instance_mounts(service, volumes)
    validate_dependencies(name, service, services)


def validate_limits(service):
    if not isinstance(service.get("image"), str) or not IMAGE.fullmatch(service["image"]):
        raise Refused("every image must use a sha256 digest")
    if not positive_number(service.get("cpus")) or service["cpus"] > MAX_SERVICE_CPUS:
        raise Refused("every service requires finite CPU limits")
    memory = memory_mib(service.get("mem_limit"))
    if memory > MAX_SERVICE_MEMORY_MIB:
        raise Refused("memory and swap limits must be equal and finite")
    if "memswap_limit" in service and memory_mib(service["memswap_limit"]) != memory:
        raise Refused("memory and swap limits must be equal and finite")
    pids = service.get("pids_limit")
    if type(pids) is not int or not 1 <= pids <= MAX_SERVICE_PIDS:
        raise Refused("every service requires a bounded PID limit")


def validate_environment(service):
    environment = service.get("environment", {})
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and ENVIRONMENT_NAME.fullmatch(key) and isinstance(value, str)
        for key, value in environment.items()
    ):
        raise Refused("environment must contain explicit string values")
    required = service.get("x-vps-required-environment", [])
    if not isinstance(required, list) or not all(
        isinstance(key, str) and environment.get(key) for key in required
    ):
        raise Refused("required service environment is missing")


def validate_healthcheck(service):
    healthcheck = service.get("healthcheck")
    if is_job(service) and healthcheck is None:
        return
    if not isinstance(healthcheck, dict) or set(healthcheck) - HEALTHCHECK_FIELDS:
        raise Refused("every long-running service requires a healthcheck")
    test = healthcheck.get("test")
    if (
        not isinstance(test, list)
        or len(test) < 2
        or test[0] not in ("CMD", "CMD-SHELL")
        or not all(isinstance(argument, str) for argument in test)
    ):
        raise Refused("invalid healthcheck command")
    retries = healthcheck.get("retries", 3)
    if type(retries) is not int or not 1 <= retries <= 10:
        raise Refused("invalid healthcheck retries")
    for key in ("interval", "timeout", "start_period"):
        if key in healthcheck and not (
            isinstance(healthcheck[key], str) and DURATION.fullmatch(healthcheck[key])
        ):
            raise Refused("invalid healthcheck duration")


def validate_process_options(service):
    if not is_job(service) and service.get("restart", "unless-stopped") not in RESTART_POLICIES:
        raise Refused("invalid restart policy")
    for key in ("command", "entrypoint"):
        if key in service and not is_command(service[key]):
            raise Refused("invalid container command")
    if "read_only" in service and type(service["read_only"]) is not bool:
        raise Refused("invalid readonly flag")
    for key in ("user", "working_dir"):
        if key in service and (not isinstance(service[key], str) or "\x00" in service[key]):
            raise Refused("invalid service option")


def is_command(value):
    if isinstance(value, str):
        return True
    return isinstance(value, list) and all(isinstance(argument, str) for argument in value)


def instance_mounts(service, volumes):
    mounts = service.get("volumes", [])
    if not isinstance(mounts, list):
        raise Refused("invalid service volumes")
    return [instance_mount(mount, volumes) for mount in mounts]


def instance_mount(mount, volumes):
    long_form = long_mount(mount) if isinstance(mount, str) else mount
    if (
        not isinstance(long_form, dict)
        or set(long_form) - MOUNT_FIELDS
        or long_form.get("type") != "volume"
        or not isinstance(long_form.get("source"), str)
        or long_form["source"] not in volumes
    ):
        raise Refused("only instance-owned volume mounts are accepted")
    if (
        not is_volume_target(long_form.get("target"))
        or type(long_form.get("read_only", False)) is not bool
    ):
        raise Refused("invalid volume target")
    return copy.deepcopy(long_form)


def long_mount(text):
    pieces = text.split(":")
    if len(pieces) not in (2, 3) or (len(pieces) == 3 and pieces[2] != "ro"):
        raise Refused("only named volume mounts are accepted")
    return {
        "type": "volume",
        "source": pieces[0],
        "target": pieces[1],
        "read_only": len(pieces) == 3,
    }


def is_volume_target(target):
    return (
        isinstance(target, str)
        and target.startswith("/")
        and ".." not in target.split("/")
        and "$" not in target
    )


def validate_dependencies(name, service, services):
    dependencies = service.get("depends_on", {})
    if not isinstance(dependencies, dict):
        raise Refused("dependencies require explicit health conditions")
    for dependency, settings in dependencies.items():
        if (
            dependency not in services
            or dependency == name
            or not isinstance(settings, dict)
            or set(settings) != {"condition"}
            or settings["condition"] not in DEPENDENCY_CONDITIONS
        ):
            raise Refused("invalid dependency")
        waits_for_completion = settings["condition"] == "service_completed_successfully"
        if is_job(services[dependency]) != waits_for_completion:
            raise Refused("dependency condition must match job or service")


def require_acyclic(services):
    """The runtime starts dependencies first; jobs included, any cycle would never start."""
    finished = set()

    def visit(name, path):
        if name in path:
            raise Refused("cyclic service dependency")
        if name in finished:
            return
        for dependency in services[name].get("depends_on", {}):
            visit(dependency, path | {name})
        finished.add(name)

    for name in services:
        visit(name, frozenset())


def runtime_service(name, service, instance, volumes, routes):
    submitted = {
        key: value for key, value in escape(service).items() if key not in PLATFORM_EXTENSIONS
    }
    return {
        **submitted,
        "memswap_limit": service["mem_limit"],
        "labels": labels(instance),
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "logging": copy.deepcopy(LOGGING),
        **restart_settings(service),
        "volumes": instance_mounts(service, volumes),
        **published_ports(name, routes),
    }


def restart_settings(service):
    if is_job(service):
        return {"profiles": [INIT_PROFILE], "restart": "no"}
    return {"restart": service.get("restart", "unless-stopped")}


def published_ports(name, routes):
    ports = [
        {
            "target": route["port"],
            "published": upstream_port(route),
            "host_ip": "127.0.0.1",
            "protocol": "tcp",
        }
        for route in routes
        if route["service"] == name
    ]
    if not ports:
        return {}
    return {"ports": ports}


def allocate_routes(routes, policy, instance, existing, services):
    if not isinstance(routes, list) or len(routes) > MAX_ROUTES:
        raise Refused("invalid routes")
    previous = existing.get(instance, {}).get("routes", [])
    occupied = {
        upstream_port(route)
        for key, record in existing.items()
        if key != instance
        for route in record.get("routes", [])
    }
    allocated = []
    for route in routes:
        require_instance_route(route, policy, instance, services, allocated)
        if any(
            item.get("hostname") == route["hostname"]
            for key, record in existing.items()
            if key != instance
            for item in record.get("routes", [])
        ):
            raise Refused("route hostname is already owned by another instance")
        taken = occupied | {upstream_port(item) for item in allocated}
        port = reused_port(previous, route) or free_port(policy, taken)
        allocated.append({**route, "upstream": "127.0.0.1:" + port})
    return allocated


def require_instance_route(route, policy, instance, services, allocated):
    if (
        not isinstance(route, dict)
        or set(route) != ROUTE_FIELDS
        or not policy.owns_hostname(route["hostname"], instance)
        or any(item["hostname"] == route["hostname"] for item in allocated)
    ):
        raise Refused("route hostname must belong to this instance namespace")
    if (
        not isinstance(route["service"], str)
        or route["service"] not in services
        or is_job(services[route["service"]])
        or type(route["port"]) is not int
        or not 1 <= route["port"] <= 65535
    ):
        raise Refused("route must target an HTTP service port")


def reused_port(previous, route):
    for item in previous:
        if item["service"] == route["service"] and item["port"] == route["port"]:
            return upstream_port(item)
    return None


def free_port(policy, taken):
    for number in range(policy["port_start"], policy["port_end"] + 1):
        if str(number) not in taken:
            return str(number)
    raise Refused("no loopback ports are available")


def stop_grace_seconds(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*[sm]", value):
        raise Refused("invalid stop grace period")
    seconds = int(value[:-1]) * (60 if value[-1] == "m" else 1)
    if seconds > 300:
        raise Refused("stop grace period exceeds limit")
    return seconds
