# Application contract — protocol version 1

An application deploys from its own repository with the `ny.vps.app` role. The role renders the application Compose on the workstation, then the `ny.vps.deploy_instance` module sends a JSON request to `sudo -n /usr/local/sbin/vpsctl request` on the VPS. The controller decides admission, applies Compose, and publishes the route.

The full example is in [`examples/application/deploy`](../examples/application/deploy).

## Install the collection

In the application repository, `deploy/ansible/requirements.yml` pins a reviewed release by its full SHA:

```yaml
collections:
  - name: https://github.com/ny-randriantsarafara/vps-services.git#/collections/ansible_collections/ny/vps
    type: git
    version: <40-character SHA of the approved release commit>
```

Never `main` or a branch. The server and collection must speak the same protocol: a request from another protocol is refused before any mutation.

## Role `ny.vps.app`

| Variable | Required | Description |
| --- | --- | --- |
| `app_application` | yes | Key registered on the VPS: lowercase, digits, hyphens, at most 32 characters, without suffix `-prod`, `-staging`, or `-pr-<n>` |
| `app_environment` | yes | `prod`, `staging`, or `preview` |
| `app_pull_request` | preview only | PR number; refused for prod and staging |
| `app_generation` | apply, plan | Increasing integer for the same instance |
| `app_operation` | no | `apply` (default), `plan`, `destroy`, `renew`, `status`, `logs` |
| `app_compose_template` | apply, plan | Jinja template for the application Compose |
| `app_routes` | no | HTTP routes; `[]` by default |
| `app_storage_budget_gib` | apply, plan | Instance data growth budget, in GiB |
| `app_reopen` | no | `true` to recreate a closed preview |
| `app_logs_tail` | no | Log lines for `logs` (1 to 1000, default 100) |
| `app_render_output` | no | Local `0600` file to write the rendered delivery, for inspection |

In check mode (`--check`), `apply` becomes `plan`: no reservation. `destroy` and `renew` are not simulated and respond `not_verified` without sending anything.

Identity is the SSH deploy account: one nonprod account for staging and previews, a separate account for production. The request never chooses its identity.

## Request

| Field | Operations | Rule |
| --- | --- | --- |
| `protocol` | all | `1` |
| `operation` | all | `apply`, `plan`, `destroy`, `renew`, `status`, `logs` |
| `application`, `environment` | all | Instance identity |
| `pull_request` | preview | Integer from 1 to 2147483647 |
| `generation` | apply, plan, destroy, renew | Positive integer |
| `compose`, `routes`, `storage_budget_gib`, `reopen` | apply, plan | Refused for other operations |
| `tail` | logs | 1 to 1000 |

The role fills these fields; an unknown field or duplicate JSON key refuses the request. Maximum size: 1 MiB.

## Compose subset

Accepted sections: `services` (1 to 16) and `volumes` (at most 16, declared `{}`). Everything else is refused: `build`, `include`, `extends`, `env_file`, `networks`, `ports`, `privileged`, `cap_add`, `devices`, `network_mode`, `pid`, `ipc`, `container_name`, `deploy`, etc.

| Service field | Rule |
| --- | --- |
| `image` | Required, by digest: `registry/image:tag@sha256:<64 hex>` |
| `cpus` | Required, > 0 and ≤ 3 |
| `mem_limit` | Required, ≤ 6 GiB (`384m`, `1g`, or bytes) |
| `memswap_limit` | Equal to `mem_limit` if present; the controller enforces it |
| `pids_limit` | Required, 1 to 1024 |
| `environment` | String dictionary; `$` is escaped, no Compose interpolation |
| `x-vps-required-environment` | Variable names that must be present and non-empty |
| `healthcheck` | Required for a long-lived service: `test` as `CMD`/`CMD-SHELL`, `interval`, `timeout`, `start_period` (`ms`, `s`, `m`), `retries` 1 to 10 |
| `depends_on` | Long form: `service_healthy` to a service, `service_completed_successfully` to a job; no cycle |
| `volumes` | `name:/path[:ro]` or long form `type: volume`; only volumes declared by the instance |
| `command`, `entrypoint`, `user`, `working_dir`, `read_only` | Free within their type |
| `restart` | `no`, `on-failure`, or `unless-stopped` (default) |
| `x-vps-init` | `true` for an initialization job |

One replica per service. Admission sums **all** services, jobs included.

The controller adds to each service: `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `json-file` logs 10 MiB × 3, labels `vps.platform.*`, network and volumes named `vps-<instance>`. It then checks these values on real containers with `docker inspect` before declaring the instance ready.

### Practical consequences

- With no capabilities, an image that starts as root then drops user fails. Declare `user:` explicitly (the example runs Postgres as `70:70`).
- The healthcheck tool must exist in the image. For Postgres, test over TCP (`pg_isready --host 127.0.0.1`): during init the temporary server listens on the Unix socket only, and a socket test would mark the database ready too early.
- Each service has 120 s to become healthy; each job 300 s to finish.

### Initialization jobs

A service with `x-vps-init: true` runs with `docker compose run --rm` before services that depend on it, **on every delivery**. It must be idempotent, for example load fixtures only into an empty database. It needs no healthcheck and gets no route.

## Routes and names

While `vps_domain` is empty on the VPS, every route is refused: the instance stays reachable only on its loopback ports, and `http_status` is `unconfigured`.

An instance publishes its primary name and, if needed, names one label below. Each name at most once, up to 16 routes:

| Instance | Primary name | Secondary names |
| --- | --- | --- |
| `exemple-prod` | `exemple.<domain>` | `<prefix>.exemple.<domain>` |
| `exemple-staging` | `exemple-staging.<domain>` | `<prefix>.exemple-staging.<domain>` |
| `exemple-pr-42` | `exemple-pr-42.<domain>` | `<prefix>.exemple-pr-42.<domain>` |

`<prefix>` is a single label: one lowercase letter then at most 31 lowercase letters or digits (`cms`, `api`). Two instances have distinct primary names, so neither can publish another’s name. A cookie set on the primary name (`Domain=exemple-pr-42.<domain>`) covers its secondary names without leaving the instance. Wildcard DNS `*.<domain>` covers both levels.

```yaml
app_routes:
  - {hostname: exemple-pr-42.apps.example.net, service: web, port: 3000}
  - {hostname: api.exemple-pr-42.apps.example.net, service: api, port: 8080}
```

`port` is the container port. The controller leases a `127.0.0.1` port per route in 20000–29999, keeps it across updates, and never shares it. All instance routes must respond on loopback before publication; `http_status` is `ready` when all respond publicly, HTTPS only.

## Generations

- Each `apply` carries a generation greater than the previous one for the instance. An older generation is refused (`stale delivery generation`).
- Replaying the same generation with the same delivery changes nothing (`delivery already current`). The same generation with a different delivery is refused.
- `destroy` leaves a tombstone. A closed preview is recreated only with `app_reopen: true` and a generation above the tombstone: a late delivery does not revive a closed PR.

## Response

The role shows public fields: `instance`, `status`, `reason`, and when applicable `local_health`, `http_status`, `disk_warning`, `runtime_present`, `logs`, `occupants`, `audit`. Never the request, Compose, or secrets.

| Status | Meaning |
| --- | --- |
| `ready` | Delivery healthy locally; `http_status` indicates public reachability |
| `planned` | Admissible now; `apply` rechecks under the lock |
| `refused` | Refused before mutation; `reason` explains, the task fails |
| `failed` | Failure after reservation; the slot stays reserved until intervention or expiration |
| `destroyed` | Preview resources verified absent |
| `renewed` | Preview expiration extended by 72 h |
| `logs` | Instance logs, capped at 256 KiB |
| `not_verified` | Check mode: `destroy` or `renew` not simulated |

For `status`, `status` repeats the registered state (`preparing`, `ready`, `failed`, `deleting`) or `absent`, with `runtime_present`.

Third preview refusal:

```json
{
  "status": "refused",
  "reason": "global preview limit reached; no existing preview is evicted",
  "occupants": [
    {"instance": "alpha-pr-1", "status": "ready", "expires_at": 1791800000.0},
    {"instance": "beta-pr-7", "status": "ready", "expires_at": 1791900000.0}
  ]
}
```

`expires_at` is a Unix timestamp. `audit: unavailable` means the decision was applied but its audit line could not be written.

## Previews

- Expiration 72 h after the last successful delivery or last `renew`. A failure does not renew.
- `renew` accepts only a `ready` preview, with a generation at least equal to its current generation.
- When the PR closes, the application repository runs `destroy`: route removed, containers, network, and instance volumes deleted, then slot freed.
- A new preview starts from a fresh volume; an update to the same PR keeps its data.

## Secrets and logs

- Values come from a private file outside Git (`-e @/private/path.yml`), never from a global `.env`.
- The role masks render and request (`no_log`, `diff: false`). Normalized Compose, which contains values, stays private on the VPS (`0600`).
- `logs` returns what the application writes: an application that logs its secrets exposes them. The controller notes this in `reason`.

## Commands

From the root of an application repository:

```bash
ansible-galaxy collection install -r deploy/ansible/requirements.yml

ansible-playbook -i deploy/ansible/inventory.yml deploy/ansible/deploy.yml \
  -e target_environment=preview -e pull_request_number=42 -e release_generation=7 \
  -e exemple_web_image=registry.example.net/exemple/web@sha256:<digest> \
  -e @/private/path/exemple-preview.yml

# Plan without reservation
ansible-playbook ... --check

# PR close
ansible-playbook -i deploy/ansible/inventory.yml deploy/ansible/deploy.yml \
  -e target_environment=preview -e pull_request_number=42 -e release_generation=8 -e operation=destroy
```

The application inventory verifies the server host key (`StrictHostKeyChecking=yes` and repository `known_hosts`), like the platform inventory.

### Extra names, onboarding, and graceful stop

Root policy `instance_hostnames` maps an exact instance to a list of extra DNS names. An application cannot change this list or take a name owned by another instance. Historical names and prefixes remain accepted.

Root policy `onboarding_guards` maps an explicitly allowed name to `{path: /api/onboarding, step: user}`. Before opening, Caddy responds HTTP 403 with `private setup required`. Only two responses open the proxy: HTTP 200 containing a JSON list with a single `user` step and `done: true`, or HTTP 404 with the exact body `404: Not Found`, returned by Home Assistant when all onboarding steps are done and the API is no longer served. Network error, limit exceeded, or wrong response keeps the guard closed. Creation `/api/onboarding/users*` stays forbidden on that public route after opening, including after an application reset. SSH tunnel to the loopback port allows private setup. These rules are not application request fields.

A service may set `stop_grace_period`, a positive integer followed by `s` or `m`, capped at 300 seconds. The controller checks the matching Docker `Config.StopTimeout`. Startup timeout stays 120 seconds. `local_health: ready` means the local service responds; `http_status: protected` means its public guard is closed.
