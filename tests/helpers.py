import json
import sys
from pathlib import Path

COLLECTION = Path(__file__).resolve().parents[1] / "collections/ansible_collections/ny/vps"
FILES = COLLECTION / "roles/controller/files"
sys.path.insert(0, str(FILES))


def policy(root):
    return {
        "accounts": {
            f"{app}-ci": {"application": app, "environments": ["staging", "preview"]}
            for app in ("alpha", "beta", "gamma")
        },
        "administrators": ["admin"],
        "domain": "",
        "apps_dir": str(root / "apps"),
        "minimum_free_disk_gib": 0.1,
        "image_growth_reserve_gib": 0.1,
    }


def request(app="alpha", pr=1, generation=1, operation="apply"):
    result = {
        "protocol": 1,
        "operation": operation,
        "application": app,
        "environment": "preview",
        "pull_request": pr,
        "generation": generation,
    }
    if operation in ("apply", "plan"):
        result.update(
            compose={
                "services": {
                    "web": {
                        "image": "example/web@sha256:" + "a" * 64,
                        "cpus": 0.2,
                        "mem_limit": "384m",
                        "pids_limit": 64,
                        "environment": {"TOKEN": "private-$HOME-${secret}"},
                        "healthcheck": {
                            "test": ["CMD", "/health"],
                            "interval": "2s",
                            "timeout": "1s",
                            "retries": 2,
                        },
                    }
                },
                "volumes": {"data": {}},
            },
            routes=[],
            storage_budget_gib=2,
        )
    return result


class BoundaryRuntime:
    """Only Docker/Caddy effects are doubled; state and locking remain real."""

    def __init__(self, root):
        self.path = root / "docker-resources.json"
        self.fail_apply = False
        self.crash_apply = False
        self.fail_destroy = False
        self.available_memory_mib = 65536
        self.storage_budgets = []

    def free_memory_mib(self):
        return self.available_memory_mib

    def inventory(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def apply(self, instance, compose_path, routes, storage_budget_gib):
        self.storage_budgets.append(storage_budget_gib)
        data = self.inventory()
        data[instance] = {"owned": True, "resources": ["container", "network", "volume"]}
        self.path.write_text(json.dumps(data))
        if self.crash_apply:
            raise SystemExit("controller process interrupted")
        if self.fail_apply:
            raise RuntimeError("private-$HOME-${secret}")
        return {"local_health": "ready", "http_status": "unconfigured" if not routes else "ready"}

    def destroy(self, instance, compose_path, routes):
        if self.fail_destroy:
            raise RuntimeError("daemon unavailable")
        data = self.inventory()
        data.pop(instance, None)
        self.path.write_text(json.dumps(data))

    def logs(self, instance, tail):
        return "application log"
