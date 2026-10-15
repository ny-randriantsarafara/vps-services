# Architecture

One VPS, no orchestrator. Ansible configures the host from the operator machine; each application deploys from its own repository by calling a local server command, `vpsctl`, which decides admission and applies Compose and Caddy routes.

```text
operator machine / application repo                     Debian 13 VPS
──────────────────────────────────                     ─────────────────────────────────────────────
ansible-playbook (ny.vps.app)                          sudo -n /usr/local/sbin/vpsctl request
  renders compose.yml.j2 locally      ── SSH ──▶        │  flock lock, JSON registry
  deploy_instance module (JSON stdin)                   │  admission: slots, budgets, memory, disk
                                                        ├─▶ docker compose (project vps-<instance>)
                                                        └─▶ Caddy (Unix socket): route after readiness
```

## Components

| Component | Ansible role | Result on the host |
| --- | --- | --- |
| Host | `ny.vps.host` | Key-based administrator `vps-admin`, security updates, journal capped at 500 MiB |
| SSH | `ny.vps.ssh` | Drop-in validated with `sshd -t`: no root, keys only, no interactive authentication |
| Firewall | `ny.vps.firewall` | `vps-firewall.service`: `VPS-INPUT` and `DOCKER-USER` chains, IPv4 and IPv6, ports 22/80/443 |
| Docker | `ny.vps.docker` | Docker Engine 29.8.2, Compose 5.5.1, signed APT repo, `json-file` rotation 10 MiB × 3 |
| Ingress | `ny.vps.ingress` | Caddy 2.11.7, administration via `/run/caddy/admin.sock`, config `/etc/caddy/vps-platform.json` |
| Controller | `ny.vps.controller` | `vpsctl`, policy `/etc/vps-platform/policy.json`, deploy accounts, maintenance timer |
| Application | `ny.vps.app` | Used by application repos; not run in `platform.yml` |

`platform.yml` does not start any application container. `register-app.yml` creates deploy accounts and rewrites policy without launching a stack.

## The `vpsctl` controller

Python program (standard library) installed root-owned under `/usr/local/lib/vps-platform/vps_platform`, run via `/usr/local/sbin/vpsctl`. Policy and state paths are fixed: neither the request nor arguments can change them.

- **Identity**: the actor comes from `SUDO_UID`/`SUDO_USER`, never from the request. Policy maps each deploy account to an application and its environments; a production account is for production only.
- **Lock**: every request takes `/var/lib/vps-platform/controller.lock` (`flock`) for the whole operation. Wait is capped at `lock_timeout_seconds` (600 s); beyond that, the request is refused.
- **Registry**: `/var/lib/vps-platform/registry.json`, written atomically as `0600`. It holds instances, generations, image digests, reserved budgets, leased ports, routes, expiry, and tombstones. No secret values.
- **Private files**: `/srv/vps/apps/<application>/<env>/compose.json` (normalized Compose, secrets included) and `previous-compose.json`, mode `0600` in `0700` directories.
- **Audit**: `/var/lib/vps-platform/audit.jsonl`, one line per request: time, actor, operation, generation, digests, instance, status, reason. Never secrets or full Compose.

## Admission

Under the lock, in this order:

1. Validate identity, protocol, fields, images by digest, required environment, volumes, and routes (subset described in [APP-CONTRACT](APP-CONTRACT.md)).
2. Reconcile the registry with Docker objects labeled `vps.platform.*`. An untracked or ambiguous object blocks new admissions, with no opportunistic deletion.
3. Count slots: any registered preview, whatever its state, occupies a slot. Updating the same PR does not consume a second one. The third preview is refused with the list of occupants and their expiry.
4. Sum environment budgets, replacing the old reservation with the max of old and new while old containers still exist.
5. Check memory: a reservation increase must leave at least 512 MiB of `MemAvailable`.
6. Check disk: free space ≥ 10 GiB reserve + declared storage budgets + 2 GiB image growth, and at least 5% free inodes. After pull, space is measured again: it must still cover reserve plus the instance storage budget, or nothing starts. An image larger than expected is refused before writing data.
7. Reserve in the registry, then only create resources.

| Envelope | CPU | Memory |
| --- | --- | --- |
| All production | 1.5 vCPU | 3 GiB |
| All staging | 1 vCPU | 1 GiB |
| All previews | 2 vCPU | 2 GiB |
| One preview | 1 vCPU | 1 GiB |

These caps are admission rules: they do not physically reserve CPU and do not guarantee performance. Disk is monitored, not quota-enforced: a database can exceed its declared budget.

## Delivery

`pull` → reserve disk → services started in dependency order (`up --no-deps --wait`), init jobs with `run --rm` → check effective values with `docker inspect` (limits, `cap_drop: ALL`, `no-new-privileges`, instance network, mounts, loopback ports) → Docker health → HTTP loopback probe for each route → publish Caddy routes → public probe. Containers removed from the delivery are deleted.

An update replaces containers: interruption is possible; zero downtime is not promised. A failure leaves the instance in `failed` with its reservation, with no automatic rollback.

## Isolation

| Resource | Rule |
| --- | --- |
| Compose project | `vps-<instance>`, no `container_name` |
| Network | Bridge `vps-<instance>`, never shared |
| Volumes | `vps-<instance>-<name>`, declared by the instance; no bind mounts |
| Containers | `cap_drop: ALL`, `no-new-privileges`, CPU/memory/swap/PID limits, no privilege or host namespace |
| Ports | `127.0.0.1:<leased port>` only, range 20000–29999 assigned by the controller |
| HTTP | Primary name derived from the instance and names one label below (`cms.<instance>…`); unknown route: neutral 404 |

Caddy serves applications on `:443` only. Port 80 stays for automatic HTTPS: ACME challenges and redirect to HTTPS. No application is served in cleartext.

Docker shares the VPS kernel: this model suits trusted applications and contributors, not running hostile PR code.

## Lifecycle

| Status | Meaning | Preview slot |
| --- | --- | --- |
| `preparing` | Reservation written, delivery in progress (15 min lease) | Occupied |
| `ready` | Delivery healthy locally | Occupied |
| `failed` | Incomplete delivery or deletion, reservation kept | Occupied |
| `deleting` | Deletion in progress | Occupied |

The `vps-platform-maintenance.timer` runs `vpsctl status` then `vpsctl cleanup` every five minutes. Cleanup only affects expired previews, those abandoned in `preparing`/`failed` after their lease, or stuck in `deleting`. Production and staging are never removed by this cycle.

## Out of scope

No Kubernetes, shared Supabase, deploy daemon or HTTP API, build on the VPS, or automatic restore of old applications. Application backups belong to each application.
