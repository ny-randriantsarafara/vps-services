import copy
import math
import re
from pathlib import Path


class Refused(ValueError):
    """A safe public reason, never include submitted values."""

    def __init__(self, reason, **diagnostics):
        super().__init__(reason)
        self.diagnostics = diagnostics


DEFAULTS = {
    "accounts": {},
    "instance_hostnames": {},
    "onboarding_guards": {},
    "administrators": [],
    "domain": "",
    "preview_limit": 2,
    "preview_ttl_seconds": 259200,
    "preparing_lease_seconds": 900,
    "lock_timeout_seconds": 600,
    "budgets": {
        "prod": {"cpus": 1.5, "memory_mib": 3072},
        "staging": {"cpus": 0.5, "memory_mib": 1024},
        "preview": {"cpus": 1, "memory_mib": 2048},
    },
    "preview_instance_budget": {"cpus": 0.5, "memory_mib": 1024},
    "apps_dir": "/srv/vps/apps",
    "port_start": 20000,
    "port_end": 29999,
    "minimum_free_memory_mib": 512,
    "minimum_free_disk_gib": 10,
    "disk_warning_gib": 15,
    "image_growth_reserve_gib": 2,
    "minimum_free_inode_ratio": 0.05,
    "caddy_config": "/etc/caddy/vps-platform.json",
    "caddy_admin_socket": "/run/caddy/admin.sock",
}
NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
INSTANCE_SUFFIX = re.compile(r"-(?:prod|staging|pr-[0-9]+)\Z")


def positive_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def is_application_name(value):
    # Instance names and hostnames are derived from it; an environment-like suffix would collide.
    return (
        isinstance(value, str)
        and len(value) <= 32
        and bool(NAME.fullmatch(value))
        and not INSTANCE_SUFFIX.search(value)
    )


class Policy:
    def __init__(self, data):
        if not isinstance(data, dict) or set(data) - set(DEFAULTS):
            raise Refused("invalid host policy")
        self.data = copy.deepcopy(DEFAULTS)
        self.data.update(copy.deepcopy(data))
        for key in (
            "preview_limit",
            "preview_ttl_seconds",
            "preparing_lease_seconds",
            "lock_timeout_seconds",
            "port_start",
            "port_end",
        ):
            if type(self.data[key]) is not int or self.data[key] < 1:
                raise Refused("invalid host policy")
        if not 1024 <= self.data["port_start"] <= self.data["port_end"] <= 65535:
            raise Refused("invalid host port range")
        for path in ("apps_dir", "caddy_config", "caddy_admin_socket"):
            if not isinstance(self.data[path], str) or not Path(self.data[path]).is_absolute():
                raise Refused("host paths must be absolute")
        domain = self.data["domain"]
        if not isinstance(domain, str) or (
            domain and not re.fullmatch(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain)
        ):
            raise Refused("invalid host domain")
        if not isinstance(self.data["accounts"], dict) or not isinstance(
            self.data["administrators"], list
        ):
            raise Refused("invalid host identities")
        for account in self.data["accounts"].values():
            if (
                not isinstance(account, dict)
                or set(account) != {"application", "environments"}
                or not is_application_name(account["application"])
            ):
                raise Refused("invalid host account")
            if not isinstance(account["environments"], list) or not set(
                account["environments"]
            ) <= {"prod", "staging", "preview"}:
                raise Refused("invalid host environments")
            if "prod" in account["environments"] and len(account["environments"]) != 1:
                raise Refused("production identity must be separate")
        self._validate_ingress()
        for budget in [*self.data["budgets"].values(), self.data["preview_instance_budget"]]:
            if set(budget) != {"cpus", "memory_mib"} or not all(
                positive_number(v) for v in budget.values()
            ):
                raise Refused("invalid host budget")
        if set(self.data["budgets"]) != {"prod", "staging", "preview"} or not all(
            positive_number(self.data[key])
            for key in ("minimum_free_disk_gib", "minimum_free_memory_mib")
        ):
            raise Refused("invalid host budget")

    def _validate_ingress(self):
        from .compose import is_instance_hostname

        aliases = self["instance_hostnames"]
        guards = self["onboarding_guards"]
        if not isinstance(aliases, dict) or not isinstance(guards, dict):
            raise Refused("invalid host ingress policy")
        applications = {account["application"] for account in self["accounts"].values()}
        owners = {}
        for instance, hostnames in aliases.items():
            if (
                not isinstance(instance, str)
                or not re.fullmatch(r"[a-z][a-z0-9-]*-(?:prod|staging|pr-[1-9][0-9]*)", instance)
                or not isinstance(hostnames, list)
            ):
                raise Refused("invalid instance hostname policy")
            application = re.sub(r"-(?:prod|staging|pr-[0-9]+)$", "", instance)
            if not is_application_name(application):
                raise Refused("invalid instance hostname policy")
            applications.add(application)
            for hostname in hostnames:
                if not valid_hostname(hostname) or hostname in owners:
                    raise Refused("invalid or colliding instance hostname")
                owners[hostname] = instance
        for hostname, owner in owners.items():
            for application in applications:
                for environment in ("prod", "staging"):
                    instance = application + "-" + environment
                    if instance != owner and is_instance_hostname(
                        hostname, instance, self["domain"]
                    ):
                        raise Refused("alias cannot steal an instance namespace")
            if self["domain"] and hostname.endswith("." + self["domain"]):
                labels = hostname[: -(len(self["domain"]) + 1)].split(".")
                namespace = labels[-1]
                if re.search(r"-(?:staging|pr-[1-9][0-9]*)$", namespace):
                    if (
                        not is_instance_hostname(hostname, namespace, self["domain"])
                        or namespace != owner
                    ):
                        raise Refused("alias cannot steal an instance namespace")
        for hostname, guard in guards.items():
            owned = hostname in owners or any(
                is_instance_hostname(hostname, app + "-prod", self["domain"])
                or is_instance_hostname(hostname, app + "-staging", self["domain"])
                for app in applications
            )
            if (
                not valid_hostname(hostname)
                or not owned
                or not isinstance(guard, dict)
                or set(guard) != {"path", "step"}
            ):
                raise Refused("invalid onboarding guard")
            if guard != {"path": "/api/onboarding", "step": "user"}:
                raise Refused("invalid onboarding guard endpoint")

    def owns_hostname(self, hostname, instance):
        from .compose import is_instance_hostname

        return is_instance_hostname(hostname, instance, self["domain"]) or hostname in self[
            "instance_hostnames"
        ].get(instance, [])

    def __getitem__(self, key):
        return self.data[key]

    def authorize(self, actor, application=None, environment=None, admin=False):
        if actor in self["administrators"]:
            return
        account = self["accounts"].get(actor)
        if (
            admin
            or not account
            or account["application"] != application
            or environment not in account["environments"]
        ):
            raise Refused("identity is not authorized")


def identity(payload):
    application = payload.get("application")
    environment = payload.get("environment")
    if not is_application_name(application):
        raise Refused("invalid application identity")
    if environment not in ("prod", "staging", "preview"):
        raise Refused("invalid environment")
    if environment == "preview":
        pr = payload.get("pull_request")
        if type(pr) is not int or not 1 <= pr <= 2147483647:
            raise Refused("invalid pull request")
        suffix = f"pr-{pr}"
    else:
        if "pull_request" in payload:
            raise Refused("pull request is only allowed for previews")
        suffix = environment
    return application, environment, suffix, f"{application}-{suffix}"


def valid_hostname(value):
    return (
        isinstance(value, str)
        and len(value) <= 253
        and all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in value.split(".")
        )
        and "." in value
    )
