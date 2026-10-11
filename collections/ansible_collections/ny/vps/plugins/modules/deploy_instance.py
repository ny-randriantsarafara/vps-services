#!/usr/bin/python

DOCUMENTATION = r"""
---
module: deploy_instance
short_description: Send one protocol version 1 request to the VPS controller
description:
  - Sends a single JSON request to C(sudo -n /usr/local/sbin/vpsctl request) on the VPS.
  - The controller derives the identity from the SSH account; the request cannot choose it.
  - In check mode, C(apply) becomes C(plan), which reserves nothing. C(destroy) and C(renew)
    are not simulated and report C(not_verified).
version_added: "1.0.0"
author: Nyhasina Randriantsarafara
options:
  operation:
    description: Controller operation.
    type: str
    choices: [apply, plan, destroy, renew, status, logs]
    required: true
  application:
    description: Application key registered on the VPS.
    type: str
    required: true
  environment:
    description: Target environment of the instance.
    type: str
    choices: [prod, staging, preview]
    required: true
  pull_request:
    description: Pull request number, required for previews only.
    type: int
  generation:
    description: Monotonic delivery generation of the instance.
    type: int
  compose:
    description: Rendered Compose services and volumes accepted by the controller.
    type: dict
  routes:
    description: HTTP routes, each with C(hostname), C(service) and C(port).
    type: list
    elements: dict
  storage_budget_gib:
    description: Declared data growth budget of the instance, in GiB.
    type: float
  reopen:
    description: Explicitly recreate a preview closed by an earlier destruction.
    type: bool
    default: false
  tail:
    description: Number of log lines for C(logs).
    type: int
notes:
  - The request may contain application secrets. It is never returned or logged.
"""

EXAMPLES = r"""
- name: Deliver the preview of pull request 42
  ny.vps.deploy_instance:
    operation: apply
    application: exemple
    environment: preview
    pull_request: 42
    generation: 123
    compose: "{{ rendered_compose }}"
    routes: []
    storage_budget_gib: 2
  no_log: true
"""

RETURN = r"""
instance:
  description: Instance name, for example C(exemple-pr-42).
  type: str
  returned: when the controller answered
status:
  description: Controller status, for example C(ready), C(planned), C(destroyed) or C(not_verified).
  type: str
  returned: always
reason:
  description: Non-sensitive explanation of the status.
  type: str
  returned: always
local_health:
  description: Local readiness of the instance.
  type: str
  returned: after apply
http_status:
  description: Public HTTP and TLS reachability, separate from local health.
  type: str
  returned: after apply
"""

import json

from ansible.module_utils.basic import AnsibleModule

VPSCTL = ["/usr/bin/sudo", "-n", "/usr/local/sbin/vpsctl", "request"]
PROTOCOL = 1
REQUIRED_RESPONSE_FIELDS = ("changed", "instance", "status", "reason")
PUBLIC_FIELDS = (
    *REQUIRED_RESPONSE_FIELDS,
    "local_health",
    "http_status",
    "disk_warning",
    "runtime_present",
    "logs",
    "occupants",
    "audit",
)
OPERATIONS = ("apply", "plan", "destroy", "renew", "status", "logs")
DEPLOYMENT_OPERATIONS = ("apply", "plan")
DEPLOYMENT_FIELDS = ("compose", "routes", "storage_budget_gib", "reopen")
GENERATION_OPERATIONS = ("apply", "plan", "destroy", "renew")
UNSIMULATED_OPERATIONS = ("destroy", "renew")


class ProtocolError(Exception):
    pass


def requested_operation(operation, check_mode):
    if check_mode and operation == "apply":
        return "plan"
    return operation


def build_request(params, operation):
    return {
        "protocol": PROTOCOL,
        "operation": operation,
        "application": params["application"],
        "environment": params["environment"],
        **optional_fields(params, operation),
    }


def optional_fields(params, operation):
    included = {
        "pull_request": params["environment"] == "preview",
        "generation": operation in GENERATION_OPERATIONS,
        "tail": operation == "logs" and params["tail"] is not None,
        **{field: operation in DEPLOYMENT_OPERATIONS for field in DEPLOYMENT_FIELDS},
    }
    return {field: params[field] for field, wanted in included.items() if wanted}


def parse_response(stdout):
    try:
        response = json.loads(stdout)
    except ValueError:
        raise ProtocolError from None
    if not isinstance(response, dict) or any(
        field not in response for field in REQUIRED_RESPONSE_FIELDS
    ):
        raise ProtocolError
    return response


def run(params, check_mode, call_vpsctl):
    """Return the module result; `call_vpsctl(data)` returns (returncode, stdout, stderr)."""
    if check_mode and params["operation"] in UNSIMULATED_OPERATIONS:
        return {
            "changed": False,
            "status": "not_verified",
            "reason": "check mode does not simulate this operation",
        }
    operation = requested_operation(params["operation"], check_mode)
    _returncode, stdout, _stderr = call_vpsctl(json.dumps(build_request(params, operation)))
    try:
        response = parse_response(stdout)
    except ProtocolError:
        return {
            "failed": True,
            "changed": False,
            "msg": "vpsctl returned no valid protocol response",
        }
    result = {field: response[field] for field in PUBLIC_FIELDS if field in response}
    if response["status"] in ("refused", "failed"):
        return {**result, "failed": True, "msg": response["reason"]}
    return result


def main():
    module = AnsibleModule(
        argument_spec={
            "operation": {"type": "str", "required": True, "choices": list(OPERATIONS)},
            "application": {"type": "str", "required": True},
            "environment": {
                "type": "str",
                "required": True,
                "choices": ["prod", "staging", "preview"],
            },
            "pull_request": {"type": "int"},
            "generation": {"type": "int"},
            "compose": {"type": "dict", "no_log": True},
            "routes": {"type": "list", "elements": "dict"},
            "storage_budget_gib": {"type": "float"},
            "reopen": {"type": "bool", "default": False},
            "tail": {"type": "int"},
        },
        required_if=[
            ("environment", "preview", ("pull_request",)),
            ("operation", "apply", ("generation", "compose", "routes", "storage_budget_gib")),
            ("operation", "plan", ("generation", "compose", "routes", "storage_budget_gib")),
            ("operation", "destroy", ("generation",)),
            ("operation", "renew", ("generation",)),
        ],
        supports_check_mode=True,
    )
    result = run(
        module.params,
        module.check_mode,
        lambda data: module.run_command(VPSCTL, data=data, binary_data=True),
    )
    public_result = {key: value for key, value in result.items() if key != "failed"}
    if result.get("failed"):
        module.fail_json(**public_result)
    module.exit_json(**public_result)


if __name__ == "__main__":
    main()
