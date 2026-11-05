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
| Docker | `ny.vps.docker` | Docker Engine 29.9.3, Compose 5.7.0, signed APT repo, `json-file` rotation 10 MiB × 3 |
| Ingress | `ny.vps.ingress` | Caddy 2.11.7, administration via `/run/caddy/admin.sock`, config `/etc/caddy/vps-platform.json` |
| Controller | `ny.vps.controller` | `vpsctl`, policy `/etc/vps-platform/policy.json`, deploy accounts, maintenance timer |
| Observability (opt-in) | `ny.vps.observability` | Official Alloy 1.21.3, private credentials, loopback diagnostics, bounded best-effort telemetry to personal Grafana Cloud |
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
3. Count slots: any registered preview, whatever its state, occupies a slot. Updating the same PR does not consume a second one. With the production inventory cap of one, a second preview is refused with the list of occupants and their expiry.
4. Sum environment budgets and the configured global application envelope (6528 MiB on this VPS; collection default 6144 MiB). The transition reserves per-service max(observed current replicas, new service), with removed/renamed services retained separately; live old one-off jobs and new init jobs are additive. It never drops below a prior failed aggregate reservation until verification succeeds. Unchanged service shapes still update at their normal envelope. Successfully `retired` records reserve no CPU/memory; their retained disk budgets still count. `retiring` and failed records retain compute reservations.
5. Check memory: a reservation increase must leave at least 512 MiB of `MemAvailable`.
6. Check disk: free space ≥ 10 GiB reserve + declared storage budgets + 2 GiB image growth, and at least 5% free inodes. After pull, space is measured again: it must still cover reserve plus the instance storage budget, or nothing starts. An image larger than expected is refused before writing data.
7. Reserve in the registry, then only create resources.

| Envelope | CPU | Memory |
| --- | --- | --- |
| All production | 3.35 vCPU | 5504 MiB |
| All legacy staging | 2 vCPU | 2048 MiB |
| All previews (one slot) | 1 vCPU | 1024 MiB |
| One preview | 1 vCPU | 1 GiB |

The global application memory ceiling on this VPS is 6528 MiB. The full production envelope, including Vaultwarden (5504 MiB), plus one 1024 MiB preview fits that ceiling. The 5 November host read found 7757.9 MiB physical RAM and 5793.4 MiB available; the cap leaves 1229.9 MiB for the host. The collection default remains 6144 MiB, and measured free-memory checks remain independent. CPU shares favor production (2048 versus 512), without changing existing service hard limits. These caps are admission rules: they do not physically reserve CPU and do not guarantee performance. Disk is monitored, not quota-enforced: a database can exceed its declared budget.

## Delivery

`pull` → reserve disk → services started in dependency order (`up --no-deps --wait`), init jobs with `run --rm` → check effective values with `docker inspect` (limits, `cap_drop: ALL`, `no-new-privileges`, instance network, mounts, loopback ports) → Docker health → HTTP loopback probe for each route → publish Caddy routes → public probe. Containers removed from the delivery are deleted.

Same-generation protocol-v1 retries accept the exact legacy fingerprint with only newly server-owned CPU shares absent; real changes still require a newer generation. An update replaces containers: interruption is possible; zero downtime is not promised. A failure leaves the instance in `failed` with its reservation, with no automatic rollback.

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
| `retiring` | Administrator staging retirement incomplete; compute reservation held | n/a |
| `retired` | Staging compute absent, routes withdrawn, named volumes and private Compose retained | n/a |

The `vps-platform-maintenance.timer` runs `vpsctl status` then `vpsctl cleanup` every five minutes. Cleanup only affects expired previews, those abandoned in `preparing`/`failed` after their lease, or stuck in `deleting`. Production and staging are never removed by this cycle. Only administrators may call `retire-staging`; it is outside protocol v1 and inaccessible to application sudo identities. Retirement fences future app delivery and retains registry ownership. Unexpected compute objects for a retired record block admission until reconciled.

## Out of scope

No Kubernetes, shared Supabase, deploy daemon or HTTP API, build on the VPS, or automatic restore of old applications. No daily or weekly backup jobs are introduced; the existing OVH backup remains.


## HTTP request telemetry

Caddy uses bounded global metrics without per-host labels. Managed routes map to static application/environment access loggers; unknown hosts are not logged. Source encoding deletes the complete request object and response headers before writing: no URI, IP, host, credentials or headers enter the telemetry file. The single private file rotates at 10 MiB with two retained rotations. It is excluded from the default runtime logger to prevent duplicate raw access output.

Alloy derives per-application/status request counters and fixed-bucket latency histograms from these sanitized records, with a fixed application/environment allowlist, bounded three-digit status codes and no host/path/method labels. It exports only the numeric metrics; access records are not exported to Loki. Counter resets on collector restart are handled with PromQL rate/increase. New collectors start at the file end to avoid replaying old traffic as current requests. Blackbox probes remain a separate availability signal.


Recent 5xx alerting uses a bounded gauge containing the sanitized Caddy server event time, so lazy counter creation, collector resets and idle recreation cannot hide the first observed error. The alert resolves after five event-time minutes. The independent registry bridge publishes its real write time; an old success file continually re-scraped by Alloy is detected as stale, while explicit failure and missing-series checks remain.
