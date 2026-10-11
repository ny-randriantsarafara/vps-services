"""Admission and lifecycle under one host lock. Answers never echo submitted values."""

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import NamedTuple

from .compose import IMAGE, normalize
from .policy import Policy, Refused, identity, positive_number
from .state import Registry, append_json_line, atomic_json, private_directory

REQUEST_FIELDS = {
    "protocol",
    "operation",
    "application",
    "environment",
    "pull_request",
    "generation",
    "compose",
    "routes",
    "storage_budget_gib",
    "reopen",
    "tail",
}
OPERATIONS = ("apply", "plan", "destroy", "renew", "status", "logs")
DEPLOYMENT_OPERATIONS = ("apply", "plan")
DEPLOYMENT_FIELDS = {"compose", "routes", "storage_budget_gib", "reopen"}
GENERATION_OPERATIONS = ("apply", "plan", "destroy", "renew")
MAX_GENERATION = 9223372036854775807
MAX_STORAGE_GIB = 1024
MAX_LOG_LINES = 1000
GIB = 1073741824
STATUS_FIELDS = (
    "instance",
    "environment",
    "generation",
    "status",
    "images",
    "budget",
    "storage_budget_gib",
    "expires_at",
    "local_health",
    "http_status",
)


class Target(NamedTuple):
    application: str
    environment: str
    suffix: str
    instance: str


class Delivery(NamedTuple):
    compose: dict
    budget: dict
    routes: list
    storage_budget_gib: float
    fingerprint: str
    images: dict


def response(instance, status, reason, changed=False, **diagnostics):
    return {
        "changed": changed,
        "instance": instance,
        "status": status,
        "reason": reason,
        **diagnostics,
    }


def validate_envelope(payload):
    if (
        not isinstance(payload, dict)
        or set(payload) - REQUEST_FIELDS
        or type(payload.get("protocol")) is not int
        or payload["protocol"] != 1
    ):
        raise Refused("invalid request or unsupported protocol")
    return Target(*identity(payload))


def validate_operation(payload):
    operation = payload.get("operation")
    if operation not in OPERATIONS:
        raise Refused("unsupported operation")
    if operation not in DEPLOYMENT_OPERATIONS and set(payload) & DEPLOYMENT_FIELDS:
        raise Refused("deployment fields are not accepted for this operation")
    generation = payload.get("generation")
    if operation in GENERATION_OPERATIONS and (
        type(generation) is not int or not 1 <= generation <= MAX_GENERATION
    ):
        raise Refused("a positive delivery generation is required")
    if "reopen" in payload and type(payload["reopen"]) is not bool:
        raise Refused("invalid reopen flag")
    return operation


def delivery_fingerprint(compose, routes, storage):
    document = json.dumps(
        {"compose": compose, "routes": routes, "storage": storage}, sort_keys=True
    )
    return hashlib.sha256(document.encode()).hexdigest()


def reservation(budget, old):
    """Failed updates reserve max(old, new): neither set of resources is assumed absent."""
    if not old:
        return budget
    return {key: max(budget[key], old["budget"][key]) for key in budget}


def reserved_storage(storage, old):
    if not old:
        return storage
    return max(storage, old["storage_budget_gib"])


def occupants(records):
    return [
        {
            "instance": record["instance"],
            "status": record["status"],
            "expires_at": record.get("expires_at"),
        }
        for record in sorted(records, key=lambda record: record["instance"])
    ]


def audit_fields(payload):
    """Only values the controller can vouch for: no raw request content reaches the audit."""
    if not isinstance(payload, dict):
        return {"operation": None, "generation": None, "images": {}}
    operation = payload.get("operation")
    generation = payload.get("generation")
    return {
        "operation": operation if operation in OPERATIONS else None,
        "generation": generation if type(generation) is int else None,
        "images": digest_images(payload.get("compose")),
    }


def digest_images(compose):
    if not isinstance(compose, dict) or not isinstance(compose.get("services"), dict):
        return {}
    return {
        name: service["image"]
        for name, service in compose["services"].items()
        if isinstance(service, dict)
        and isinstance(service.get("image"), str)
        and IMAGE.fullmatch(service["image"])
    }


class Controller:
    def __init__(self, policy, state_dir, runtime):
        self.policy = policy if isinstance(policy, Policy) else Policy(policy)
        self.registry = Registry(state_dir, self.policy["lock_timeout_seconds"])
        self.runtime = runtime

    def request(self, payload, actor):
        result = self._request(payload, actor)
        return self._audited(actor, audit_fields(payload), result)

    def status(self, actor, previews=False):
        try:
            self.policy.authorize(actor, admin=True)
            with self.registry.locked():
                state = self.registry.load()
                return self._host_status(state, previews)
        except Refused as error:
            return response(None, "refused", str(error), **error.diagnostics)
        except Exception:
            return response(None, "failed", "status failed; operator inspection required")

    def refresh_ingress(self, actor):
        try:
            self.policy.authorize(actor, admin=True)
            with self.registry.locked():
                state = self.registry.load()
                self._inventory(state, admission=True)
                statuses = self.runtime.refresh_ingress(self._routes(state))
                for record in state["instances"].values():
                    if record["status"] == "ready" and record.get("routes"):
                        values = [statuses[route["hostname"]] for route in record["routes"]]
                        record["http_status"] = (
                            "protected"
                            if "protected" in values
                            else (
                                "ready"
                                if all(value == "ready" for value in values)
                                else "unreachable"
                            )
                        )
                self.registry.save(state)
            return response(None, "ready", "ingress refreshed")
        except Refused as error:
            return response(None, "refused", str(error))
        except Exception:
            return response(None, "failed", "ingress refresh failed; operator inspection required")

    def cleanup(self, actor):
        try:
            self.policy.authorize(actor, admin=True)
            with self.registry.locked():
                state = self.registry.load()
                self._inventory(state, admission=True)
                results = self._reclaim_previews(state, actor)
        except Refused as error:
            return response(None, "refused", str(error), **error.diagnostics)
        except Exception:
            return response(None, "failed", "cleanup failed; reservations retained")
        changed = any(result["changed"] for result in results)
        if any(result["status"] == "failed" for result in results):
            return response(None, "failed", "some reservations retained", changed, results=results)
        return response(
            None, "cleaned", "preview reconciliation complete", changed, results=results
        )

    def _request(self, payload, actor):
        try:
            target = validate_envelope(payload)
        except Refused as error:
            return response(None, "refused", str(error))
        try:
            self.policy.authorize(actor, target.application, target.environment)
            operation = validate_operation(payload)
            with self.registry.locked():
                state = self.registry.load()
                return self._dispatch(operation, state, payload, actor, target)
        except Refused as error:
            return response(target.instance, "refused", str(error), **error.diagnostics)
        except Exception:
            # Dependency output, filesystem paths, environment and request values are private.
            return response(
                target.instance,
                "failed",
                "operation failed; private operator inspection required",
            )

    def _dispatch(self, operation, state, payload, actor, target):
        if operation == "status":
            return self._instance_status(state, target)
        if operation == "logs":
            return self._logs(state, target, payload.get("tail", 100))
        if operation == "destroy":
            return self._destroy(state, target.instance, payload["generation"])
        if operation == "renew":
            return self._renew(state, target, payload["generation"])
        return self._apply(state, payload, actor, target, plan=operation == "plan")

    def _audited(self, actor, fields, result):
        entry = {
            "time": round(time.time(), 3),
            "actor": actor,
            **fields,
            "instance": result["instance"],
            "status": result["status"],
            "reason": result["reason"],
            "changed": result["changed"],
        }
        try:
            append_json_line(self.registry.directory / "audit.jsonl", entry)
        except (OSError, Refused):
            return {**result, "audit": "unavailable"}
        return result

    def _path(self, application, suffix):
        return Path(self.policy["apps_dir"]) / application / suffix / "compose.json"

    def _routes(self, state, omit=None):
        return [
            route
            for key, record in state["instances"].items()
            if key != omit and record["status"] == "ready"
            for route in record.get("routes", [])
        ]

    def _inventory(self, state, admission=False):
        inventory = self.runtime.inventory()
        if not isinstance(inventory, dict) or any(
            not value.get("owned") for value in inventory.values()
        ):
            raise Refused("ambiguous runtime objects require operator reconciliation")
        if admission and set(inventory) - set(state["instances"]):
            raise Refused("untracked runtime objects block admission")
        return inventory

    def _free_disk_gib(self):
        return shutil.disk_usage(self.registry.directory).free / GIB

    def _instance_status(self, state, target):
        record = state["instances"].get(target.instance, {"status": "absent"})
        inventory = self._inventory(state)
        return response(
            target.instance,
            record["status"],
            "registered instance status",
            runtime_present=target.instance in inventory,
        )

    def _logs(self, state, target, tail):
        if (
            type(tail) is not int
            or not 1 <= tail <= MAX_LOG_LINES
            or target.instance not in state["instances"]
        ):
            raise Refused("logs require an existing instance and tail from 1 to 1000")
        self._inventory(state)
        return response(
            target.instance,
            "logs",
            "application logs may contain application-written secrets",
            logs=self.runtime.logs(target.instance, tail),
        )

    def _renew(self, state, target, generation):
        record = state["instances"].get(target.instance)
        if (
            target.environment != "preview"
            or not record
            or record["status"] != "ready"
            or generation < record["generation"]
        ):
            raise Refused("only a current healthy preview can be renewed")
        record["expires_at"] = time.time() + self.policy["preview_ttl_seconds"]
        self.registry.save(state)
        return response(target.instance, "renewed", "preview expiration renewed", True)

    def _apply(self, state, payload, actor, target, plan):
        inventory = self._inventory(state, admission=True)
        old = state["instances"].get(target.instance)
        self._require_newer_than_tombstone(state, payload, target.instance)
        if old and payload["generation"] < old["generation"]:
            raise Refused("stale delivery generation")
        delivery = self._delivery(payload, state, target.instance)
        if old and payload["generation"] == old["generation"]:
            return self._repeated_delivery(old, delivery, target.instance, inventory, plan)
        self._admit(state, target, delivery, old)
        if plan:
            return response(
                target.instance,
                "planned",
                "admissible now; apply rechecks under lock",
                disk_warning=self._free_disk_gib() < self.policy["disk_warning_gib"],
            )
        return self._deliver(state, payload, actor, target, delivery, old)

    def _require_newer_than_tombstone(self, state, payload, instance):
        tombstone = state["tombstones"].get(instance)
        if tombstone is None:
            return
        if payload["generation"] <= tombstone or not payload.get("reopen"):
            raise Refused("closed instance requires explicit reopen with a newer generation")

    def _delivery(self, payload, state, instance):
        compose, budget, routes = normalize(payload, self.policy, instance, state["instances"])
        storage = payload.get("storage_budget_gib")
        if not positive_number(storage) or storage > MAX_STORAGE_GIB:
            raise Refused("finite storage budget is required")
        return Delivery(
            compose=compose,
            budget=budget,
            routes=routes,
            storage_budget_gib=storage,
            fingerprint=delivery_fingerprint(compose, routes, storage),
            images={name: service["image"] for name, service in compose["services"].items()},
        )

    def _repeated_delivery(self, old, delivery, instance, inventory, plan):
        if old.get("fingerprint") != delivery.fingerprint:
            raise Refused("a changed delivery requires a newer generation")
        if old["status"] != "ready" or instance not in inventory:
            raise Refused("incomplete delivery requires a newer generation")
        return response(
            instance,
            "planned" if plan else "ready",
            "delivery already current",
            local_health="ready",
            http_status=old.get("http_status", "unconfigured"),
        )

    def _admit(self, state, target, delivery, old):
        others = [
            record
            for key, record in state["instances"].items()
            if key != target.instance and record["environment"] == target.environment
        ]
        reserved = reservation(delivery.budget, old)
        if target.environment == "preview":
            self._admit_preview(others, delivery.budget, old)
        self._require_environment_budget(target.environment, others, reserved)
        self._require_memory_margin(reserved, old)
        self._require_disk_reserve(
            state, target.instance, reserved_storage(delivery.storage_budget_gib, old)
        )

    def _admit_preview(self, others, budget, old):
        limit = self.policy["preview_instance_budget"]
        if budget["cpus"] > limit["cpus"] or budget["memory_mib"] > limit["memory_mib"]:
            raise Refused("preview exceeds its instance resource budget")
        if not old and len(others) >= self.policy["preview_limit"]:
            raise Refused(
                "global preview limit reached; no existing preview is evicted",
                occupants=occupants(others),
            )

    def _require_environment_budget(self, environment, others, reserved):
        envelope = self.policy["budgets"][environment]
        for key, amount in reserved.items():
            if sum(record["budget"][key] for record in others) + amount > envelope[key] + 1e-9:
                raise Refused("aggregate environment resource budget exceeded")

    def _require_memory_margin(self, reserved, old):
        previous = old["budget"]["memory_mib"] if old else 0
        increase = reserved["memory_mib"] - previous
        if increase <= 0:
            return
        if self.runtime.free_memory_mib() - increase < self.policy["minimum_free_memory_mib"]:
            raise Refused("available memory margin prevents admission")

    def _require_disk_reserve(self, state, instance, storage):
        declared = storage + sum(
            record["storage_budget_gib"]
            for key, record in state["instances"].items()
            if key != instance
        )
        required = (
            self.policy["minimum_free_disk_gib"]
            + declared
            + self.policy["image_growth_reserve_gib"]
        )
        if self._free_disk_gib() < required:
            raise Refused("disk reserve or declared storage budgets prevent admission")
        disk = os.statvfs(self.registry.directory)
        if disk.f_files and disk.f_favail / disk.f_files < self.policy["minimum_free_inode_ratio"]:
            raise Refused("inode reserve prevents admission")

    def _deliver(self, state, payload, actor, target, delivery, old):
        path = self._path(target.application, target.suffix)
        private_directory(path.parent)
        if path.exists():
            atomic_json(path.parent / "previous-compose.json", json.loads(path.read_text()))
        record = {
            "instance": target.instance,
            "application": target.application,
            "environment": target.environment,
            "suffix": target.suffix,
            "generation": payload["generation"],
            "fingerprint": delivery.fingerprint,
            "images": delivery.images,
            "budget": reservation(delivery.budget, old),
            "storage_budget_gib": reserved_storage(delivery.storage_budget_gib, old),
            "routes": delivery.routes,
            "status": "preparing",
            "lease_until": time.time() + self.policy["preparing_lease_seconds"],
            "expires_at": old.get("expires_at") if old else None,
            "actor": actor,
        }
        state["instances"][target.instance] = record
        state["tombstones"].pop(target.instance, None)
        self.registry.save(state)  # Reservation exists before any Docker or file mutation.
        try:
            atomic_json(path, delivery.compose)
            routes = self._routes(state, target.instance) + delivery.routes
            result = self.runtime.apply(target.instance, path, routes, delivery.storage_budget_gib)
        except Exception:
            record["status"] = "failed"
            self.registry.save(state)
            return response(
                target.instance, "failed", "delivery failed; resources remain reserved", True
            )
        record.update(
            status="ready",
            budget=delivery.budget,
            storage_budget_gib=delivery.storage_budget_gib,
            local_health=result["local_health"],
            http_status=result["http_status"],
        )
        if target.environment == "preview":
            record["expires_at"] = time.time() + self.policy["preview_ttl_seconds"]
        self.registry.save(state)
        return response(
            target.instance,
            "ready",
            "delivery is locally healthy",
            True,
            local_health=record["local_health"],
            http_status=record["http_status"],
        )

    def _destroy(self, state, instance, generation):
        old = state["instances"].get(instance)
        tombstone = state["tombstones"].get(instance, 0)
        if generation < max(tombstone, old["generation"] if old else 0):
            raise Refused("stale destruction generation")
        if not old:
            return self._close_absent(state, instance, generation, tombstone)
        if old["environment"] != "preview":
            raise Refused("durable instances cannot be destroyed through preview lifecycle")
        state["tombstones"][instance] = generation
        old.update(status="deleting", generation=generation)
        self.registry.save(state)
        try:
            self._inventory(state)
            path = self._path(old["application"], old["suffix"])
            self.runtime.destroy(instance, path, self._routes(state, instance))
            if instance in self._inventory(state):
                raise Refused("instance resources remain after deletion")
            shutil.rmtree(path.parent)
        except Exception:
            return response(instance, "failed", "deletion incomplete; reservation retained", True)
        del state["instances"][instance]
        self.registry.save(state)
        return response(instance, "destroyed", "preview resources verified absent", True)

    def _close_absent(self, state, instance, generation, tombstone):
        if instance in self._inventory(state):
            raise Refused("untracked instance requires operator reconciliation")
        changed = generation > tombstone
        state["tombstones"][instance] = generation
        if changed:
            self.registry.save(state)
        return response(instance, "destroyed", "instance is absent", changed)

    def _host_status(self, state, previews):
        inventory = self._inventory(state)
        records = [
            record
            for record in state["instances"].values()
            if not previews or record["environment"] == "preview"
        ]
        free = self._free_disk_gib()
        return response(
            None,
            "status",
            "host registry and runtime inventory",
            instances=[{key: record.get(key) for key in STATUS_FIELDS} for record in records],
            untracked_instances=sorted(set(inventory) - set(state["instances"])),
            disk_free_gib=round(free, 2),
            disk_warning=free < self.policy["disk_warning_gib"],
        )

    def _reclaim_previews(self, state, actor):
        now = time.time()
        reclaimable = [
            record
            for record in list(state["instances"].values())
            if record["environment"] == "preview" and is_reclaimable(record, now)
        ]
        results = []
        for record in reclaimable:
            result = self._destroy(state, record["instance"], record["generation"])
            fields = {"operation": "cleanup", "generation": record["generation"], "images": {}}
            results.append(self._audited(actor, fields, result))
        return results


def is_reclaimable(record, now):
    expired = record.get("expires_at") is not None and record["expires_at"] <= now
    abandoned = record["status"] in ("preparing", "failed") and record["lease_until"] <= now
    return expired or abandoned or record["status"] == "deleting"
