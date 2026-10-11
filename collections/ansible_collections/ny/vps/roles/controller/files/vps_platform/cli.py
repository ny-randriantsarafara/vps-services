"""Privileged entry point: no path or identity override from request/arguments."""

import argparse
import json
import os
import pwd
import sys
from pathlib import Path

from .controller import Controller, response
from .policy import Policy, Refused
from .runtime import Runtime

POLICY_PATH = Path("/etc/vps-platform/policy.json")
STATE_PATH = Path("/var/lib/vps-platform")
MAX_REQUEST = 1048576
EXIT_CODES = {"refused": 2, "failed": 1}


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused("invalid command arguments")


def parser():
    result = SafeParser(prog="vpsctl")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("request")
    commands.add_parser("status")
    commands.add_parser("cleanup")
    ingress = commands.add_parser("ingress").add_subparsers(dest="ingress_command", required=True)
    ingress.add_parser("refresh")
    previews = commands.add_parser("previews").add_subparsers(dest="preview_command", required=True)
    previews.add_parser("list")
    for name in ("destroy", "renew"):
        command = previews.add_parser(name)
        command.add_argument("--instance", required=True)
    logs = commands.add_parser("logs")
    logs.add_argument("--instance", required=True)
    logs.add_argument("--tail", type=int, default=100)
    return result


def read_request(stream):
    raw = stream.read(MAX_REQUEST + 1)
    if len(raw.encode("utf-8")) > MAX_REQUEST:
        raise Refused("request exceeds size limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
    except (ValueError, RecursionError):
        raise Refused("invalid JSON request") from None


def effective_actor():
    if os.geteuid() != 0:
        raise Refused("vpsctl requires the host sudo policy")
    sudo_uid = os.environ.get("SUDO_UID")
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_uid is None and sudo_user is None:
        return pwd.getpwuid(os.getuid()).pw_name
    if not sudo_uid or not sudo_uid.isdecimal() or not sudo_user:
        raise Refused("invalid sudo identity")
    actor = pwd.getpwuid(int(sudo_uid)).pw_name
    if actor != sudo_user or int(sudo_uid) == 0:
        raise Refused("invalid sudo identity")
    return actor


def host_controller():
    info = POLICY_PATH.stat()
    if info.st_uid != 0 or info.st_mode & 0o022 or POLICY_PATH.is_symlink():
        raise Refused("host policy ownership is unsafe")
    policy = Policy(json.loads(POLICY_PATH.read_text()))
    return Controller(policy, STATE_PATH, Runtime(policy))


def lifecycle_generation(record, operation):
    # A destruction closes the instance: its tombstone must outrank the current delivery.
    if operation == "destroy":
        return record["generation"] + 1
    return record["generation"]


def instance_payload(controller, instance, operation, tail=None):
    # Operator commands are admin-only; app accounts use the versioned request contract.
    with controller.registry.locked():
        state = controller.registry.load()
    record = state["instances"].get(instance)
    if not record or (record["environment"] != "preview" and operation != "logs"):
        raise Refused("requested instance is not available for this operation")
    payload = {
        "protocol": 1,
        "operation": operation,
        "application": record["application"],
        "environment": record["environment"],
        "generation": lifecycle_generation(record, operation),
    }
    if record["environment"] == "preview":
        payload["pull_request"] = int(record["suffix"].removeprefix("pr-"))
    if tail is not None:
        payload["tail"] = tail
    return payload


def request_payload(arguments, stdin):
    if arguments.command != "request":
        return None
    return read_request(stdin)


def instance_operation(arguments):
    if arguments.command == "logs":
        return "logs"
    return arguments.preview_command


def run_command(controller, arguments, payload, actor):
    if not isinstance(actor, str):
        raise Refused("effective identity is missing")
    if arguments.command == "request":
        return controller.request(payload, actor)
    controller.policy.authorize(actor, admin=True)
    if arguments.command == "status":
        return controller.status(actor)
    if arguments.command == "ingress":
        return controller.refresh_ingress(actor)
    if arguments.command == "cleanup":
        return controller.cleanup(actor)
    if arguments.command == "previews" and arguments.preview_command == "list":
        return controller.status(actor, previews=True)
    tail = getattr(arguments, "tail", None)
    operation = instance_operation(arguments)
    lifecycle_request = instance_payload(controller, arguments.instance, operation, tail)
    return controller.request(lifecycle_request, actor)


def run_on_host(arguments, payload):
    actor = effective_actor()
    return run_command(host_controller(), arguments, payload, actor)


def main(argv=None, *, controller=None, actor=None, stdin=None, stdout=None):
    """Injection is a Python API for tests; privileged executable exposes none of it."""
    output = stdout or sys.stdout
    try:
        arguments = parser().parse_args(argv)
        payload = request_payload(arguments, stdin or sys.stdin)
        if controller is None:
            result = run_on_host(arguments, payload)
        else:
            result = run_command(controller, arguments, payload, actor)
    except Refused as error:
        result = response(None, "refused", str(error), **error.diagnostics)
    except Exception:
        result = response(None, "failed", "host operation failed; private inspection required")
    print(json.dumps(result, allow_nan=False), file=output)
    return EXIT_CODES.get(result["status"], 0)
