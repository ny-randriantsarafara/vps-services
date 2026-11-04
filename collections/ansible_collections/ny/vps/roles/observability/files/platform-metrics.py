#!/usr/bin/python3
"""Small read-only registry/textfile bridge; no Docker, cloud or application credentials."""

import collections
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path

REGISTRY = Path("/var/lib/vps-platform/registry.json")
OUTPUT = Path("/run/alloy-platform/platform.prom")
REBOOT = Path("/var/run/reboot-required")


def render_metrics(registry=REGISTRY, reboot=REBOOT):
    lines = [
        f"node_reboot_required {int(reboot.exists())}",
        f"vps_platform_last_collection_timestamp_seconds {int(time.time())}",
    ]
    try:
        data = json.loads(registry.read_text())
        if data["protocol"] != 1 or not isinstance(data["instances"], dict):
            raise ValueError
        counts = collections.Counter()
        memory, storage = 0, 0
        for record in data["instances"].values():
            app, env, status = (record[key] for key in ("application", "environment", "status"))
            if (
                not isinstance(app, str)
                or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", app)
                or env not in ("prod", "staging", "preview")
                or status not in ("preparing", "ready", "failed", "deleting", "retiring", "retired")
            ):
                raise ValueError
            counts[(app, env, status)] += 1
            amount, disk = record["budget"]["memory_mib"], record["storage_budget_gib"]
            if not all(
                type(value) in (int, float) and math.isfinite(value) and value >= 0
                for value in (amount, disk)
            ):
                raise ValueError
            if status != "retired":
                memory += amount
            storage += disk
        lines += [
            f"vps_platform_reserved_memory_mib {memory:g}",
            f"vps_platform_storage_budget_gib {storage:g}",
        ]
        for (app, env, status), count in sorted(counts.items()):
            lines.append(
                f'vps_platform_instances{{application="{app}",environment="{env}",status="{status}"}} {count}'
            )
        lines.append("vps_platform_collect_success 1")
    except (OSError, ValueError, KeyError, TypeError):
        lines.append("vps_platform_collect_success 0")
    return "\n".join(lines) + "\n"


def main():
    fd, temporary = tempfile.mkstemp(prefix=".platform-", dir=OUTPUT.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(render_metrics())
        os.replace(temporary, OUTPUT)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
