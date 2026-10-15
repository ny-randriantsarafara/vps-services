# vps-services

Ansible platform for a single VPS (Debian 13) and the application deployment contract.

This repository configures the server: non-root administrator, key-based SSH, IPv4/IPv6 firewall, Docker, Caddy, and a local admission command, `vpsctl`. It does not deploy any application. Each application repository has its own Compose and playbook, and uses the `ny.vps` collection to request a `prod`, `staging`, or `preview` instance.

Vocabulary (application, instance, preview, preview slot, admission) is defined in the [glossary](GLOSSARY.md).

## Platform rules

- At most two previews on the VPS, all applications combined; a third is refused and none is evicted.
- Aggregate budgets (inventory, `vps_budgets`): production 1.5 vCPU / 3 GiB, staging 1 vCPU / 1 GiB, previews 2 vCPU / 2 GiB, at most one preview at 1 vCPU / 1 GiB.
- A preview expires 72 hours after its last successful delivery or last renewal; prod and staging never expire.
- Each instance has its own network, volumes, secrets, and data. Only Caddy listens on 80/443; applications publish on `127.0.0.1` only.
- Deploy accounts have neither the `docker` group nor general sudo: only `sudo -n /usr/local/sbin/vpsctl request`.
- Deployments start from application repositories (workstation or application CI; see [CI/CD](docs/CICD.md)). This repository’s CI validates; it does not deploy.

## Layout

```text
inventories/production/   VPS, administrator, deploy accounts (no secrets)
playbooks/                bootstrap.yml, platform.yml, register-app.yml
collections/ansible_collections/ny/vps/
  roles/                  host, ssh, firewall, docker, ingress, controller, app
  roles/controller/files/vps_platform/   vpsctl controller (Python, standard library)
  plugins/modules/        deploy_instance: protocol version 1 request
examples/application/     fictitious “exemple” application and its deployment
tests/                    controller, module, Ansible renders; tests/integration: local Docker
docs/                     architecture, application contract, operations, CI, migration
```

## Commands

```bash
make setup                          # .venv and pinned tools (hashes verified)
make check                          # Ruff, tests, ansible-lint, syntax, collection build
make test                           # unit tests only
make integration                    # opt-in: local Docker, vpsitest-* resources only
make collection                     # build ny.vps into dist/

make plan TARGET=vps-d9d9aca9       # platform.yml with --check --diff
make bootstrap TARGET=vps-d9d9aca9  # administrator then SSH hardening
make platform TARGET=vps-d9d9aca9   # platform, no application
make register-app TARGET=vps-d9d9aca9
```

Commands that touch a server refuse to run unless `TARGET` equals an exact inventory host name.

## Documentation

| Document | Contents |
| --- | --- |
| [Architecture](docs/ARCHITECTURE.md) | Components, admission, isolation, local state |
| [Application contract](docs/APP-CONTRACT.md) | Protocol version 1 request, Compose subset, routes, statuses, `ny.vps.app` role |
| [Operations](docs/OPERATIONS.md) | SSH host keys, bootstrap, OVH recovery, `vpsctl`, diagnostics |
| [CI/CD](docs/CICD.md) | Validation in this repo, rules for application deployments |
| [Migration](docs/MIGRATION.md) | Removal of the old Supabase stack and its workflows |
| [Design](docs/superpowers/specs/2026-10-11-ansible-vps-design.md) | Specification and decisions |
| [Multiple routes](docs/superpowers/specs/2026-10-11-multi-route-design.md) | Secondary instance names, `apps` domain, `my-media` accounts |

## Validation status

| Level | Status |
| --- | --- |
| Controller, module, and renders (`make check`) | Run locally |
| Generated configs (sshd, dockerd, iptables-nft, Caddy) | Validated with pinned tools in containers |
| Local Docker (`make integration`) | Run: two previews, third refused, distinct data, effective limits, update, targeted cleanup |
| Full Debian 13 VM (systemd, reboot, idempotence) | Not run |
| Real VPS | Provisioned: bootstrap, `platform` twice (second pass unchanged), reboot, only 22/80/443 open on IPv4/IPv6, `DOCKER-USER` filtering verified |

Instance domain: `apps.nyhasinavalona.com` (wildcard DNS `*.apps`, no Cloudflare proxy). Registered applications: `my-media` (`my-media-nonprod` and `my-media-prod` accounts), `home-assistant` (`home-assistant-prod` account), and `portfolio` (`portfolio-nonprod` and `portfolio-prod` accounts).
