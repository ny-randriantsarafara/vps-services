# Ansible VPS Services rewrite — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy stack with a usable Ansible platform and an isolated application deployment contract, with verifiable global admission.

**Architecture:** A `ny.vps` collection configures the server and provides an application role. A limited privileged local command validates requests, serializes mutations, applies Compose and Caddy routes, and expires previews. Each application repository keeps its stack and playbook.

**Tech Stack:** Debian 13, Python 3 standard library for the controller, Ansible, Docker Engine/Compose, Caddy, iptables-nft/ip6tables-nft, unittest/pytest, ansible-lint and Ruff for local checks.

**Spec:** `docs/superpowers/specs/2026-10-11-ansible-vps-design.md`

## Global Constraints

- Global VPS cap: two active previews, configurable on the host; one instance per application/PR.
- Durable instance `prod` or `staging`, preview `pr-<number>`; distinct networks, volumes, secrets, and data.
- Aggregate application budgets: production 1.5 vCPU / 3 GiB; staging 0.5 vCPU / 1 GiB; previews 1 vCPU / 2 GiB; at most one preview at 0.5 vCPU / 1 GiB.
- Preview expiration: 72 hours since successful apply or explicit renew; no prod/staging expiration.
- Manual deployments at first; no old deploy on push to main.
- No rebuild of old apps, shared Supabase, Kubernetes, daemon, or public deploy API.
- No commit, push, PR, DNS mutation, reset, or provisioning of the real VPS.
- Secrets outside Git and public output, CI accounts without docker group or general sudo, host key verification.
- Do not overwrite concurrent work in the original directory; private archive outside Git before replacement, `.git` kept.

## Shared contract version 1

The root-owned process `vpsctl request` receives JSON bounded on stdin. Policy and state paths are fixed for the privileged CLI, with no override via environment/CI arguments. An injectable Python API allows local tests without root. Install: `/usr/local/lib/vps-platform/vps_platform`, launcher `/usr/local/sbin/vpsctl`, policy `/etc/vps-platform/policy.json`, state `/var/lib/vps-platform`, instances `/srv/vps/apps`.

```json
{
  "protocol": 1,
  "operation": "apply",
  "application": "exemple",
  "environment": "preview",
  "pull_request": 42,
  "generation": 123,
  "compose": {"services": {}},
  "routes": [],
  "storage_budget_gib": 2
}
```

`compose` is YAML/JSON rendered on the app side; allowed secrets are already in the environments of the services concerned. The controller validates an explicit subset: image by digest, one replica, direct per-service limits, instance-owned named volumes, loopback HTTP ports assigned by the controller, healthchecks, declared init jobs. No `env_file`, `include`, `extends`, Docker build, socket, device, host namespace, or arbitrary application bind mount. Routes contain `hostname`, `service`, `port`; no proxy config fragments. Read/delete/renew operations use the same identity and instance; monotone generation protects apply and close. Policy has `accounts` mapping SSH user to application/environments, `administrators`, `domain` empty by default, caps and paths managed by the platform.

JSON output: `changed`, `instance`, `status`, `reason`, and non-sensitive diagnostics. No raw request, secrets, or full Compose in output. Operational exceptions are sanitary; container logs only when explicitly requested for the authorized instance, with warning that the app must avoid writing secrets there.

### Task 1: Local controller, admission, and Compose lifecycle

**Files:**
- Create: `collections/ansible_collections/ny/vps/roles/controller/files/vps_platform/{__init__,policy,compose,state,runtime,controller,cli}.py`
- Create: `collections/ansible_collections/ny/vps/roles/controller/files/{launcher.py,vpsctl}`
- Test: `tests/test_controller.py`, `tests/test_compose.py`, `tests/test_runtime.py`, `tests/helpers.py`

**Interfaces:**
- Consumes: JSON contract version 1 above and host JSON policy; effective identity passed by the CLI, never from the request.
- Produces: `Controller(policy, state_dir, runtime).request(payload, actor)`; Docker/Caddy runtime and CLI `request`, `status`, `previews list`, `previews destroy --instance`, `previews renew --instance`, `cleanup`, `logs --instance --tail`.
- Runtime is an injectable boundary; registry and flock stay real in tests.

- [ ] **Step 1: write behavioral tests before code.** Expectations are literal, including:

```python
def test_third_preview_is_refused_without_evicting_existing_instances():
    # Two distinct applications each already have an admitted preview.
    # A third request applies real policy and must be refused.
    assert third_result["status"] == "refused"
    assert instance_names == {"alpha-pr-1", "beta-pr-2"}
```

Really test concurrency via process and flock, same-PR update, per-service/aggregate limits, prod/nonprod identity, isolated data/names, refusal of dangerous configs, idempotence, secrets persisted privately but absent from registry, close/generation, crash/incomplete cleanup and TTL. Docker/Caddy calls are doubled only when they need a daemon or server.
- [ ] **Step 2: run `python -m unittest discover -s tests -v` and see missing behaviors fail.** Implement modules progressively and rerun the same test group.
- [ ] **Step 3: build the real runtime.** Use subprocess argv, bounded delays, non-sensitive stdout/stderr; keep labels and ownership checks before deletion; no global prune. Atomic private JSON, secrets escaping Compose interpolation, `0600` files, `0700` directories. Reconcile unknown states with real resources without freeing a slot blindly. Untracked app objects block new admissions.
- [ ] **Step 4: verify then review.** Real CLI tests, invalid JSON and JSON outputs, fixed paths in privileged mode, plan without mutation and status/cleanup. Provide RED/GREEN evidence and precise final contract for the Ansible role.

### Task 2: Ansible collection, server, and runnable application example

**Files:**
- Create: `ansible.cfg`, `inventories/production/{hosts.yml,group_vars/all.yml}`, `playbooks/{bootstrap,platform,register-app}.yml`
- Create: `collections/ansible_collections/ny/vps/galaxy.yml`, `roles/{host,ssh,firewall,docker,ingress,controller,app}/{tasks,handlers,defaults,templates}` as needed
- Create: `collections/ansible_collections/ny/vps/plugins/modules/deploy_instance.py`
- Create: `examples/application/deploy/{compose.yml.j2,ansible/{deploy.yml,inventory.yml,requirements.yml,environments/{preview,staging,prod}.yml}}`
- Test: `tests/test_app_module.py`, syntax/lint checks and local render of examples.

**Interfaces:**
- Consumes: CLI `vpsctl request` and real Task 1 contract. The Ansible module grants no general sudo: fixed subprocess `sudo -n /usr/local/sbin/vpsctl request`, JSON stdin, `no_log` for payload and `supports_check_mode=True` turning apply into plan.
- Produces: playbooks runnable from the workstation, safe host vars, installable/buildable collection; example without real secrets or real domain.

- [ ] **Step 1: write and run a module test before implementation.** Apply input in check mode must send `plan`, produce no reservation, keep filtered JSON output, and fail on protocol error rather than declare success.

```python
def test_check_mode_requests_plan_instead_of_apply():
    assert sent_payload["operation"] == "plan"
    assert result["changed"] is False
```

- [ ] **Step 2: create bootstrap in two phases.** Install administrator keys then test independent connection before hardening/removing initial access. `sshd -t`, validated drop-in, reload; safe state on failure; OVH recovery documented. Non-root administrator account, application accounts explicitly registered without docker group, sudoers validated with visudo.
- [ ] **Step 3: create idempotent platform.** Signed APT Docker Debian 13 with verified exact versions, Compose, log limits; SSH, IPv4/IPv6 INPUT and DOCKER-USER rules restored after daemon/reboot without removing Docker NAT; Caddy systemd, Unix admin socket, controlled routes, no old domain. Cleanup/disk pressure timer 5 min. Controller installed root-owned, private config and policy consistent with Task 1. No app container started by platform.
- [ ] **Step 4: create app role and example.** Compose render from app repo, isolated limits and volumes, test database and synthetic fixtures in a pinned image; readiness required. Working local collection reference for smoke test, plus exact procedure to pin a release SHA without a fake SHA. `no_log`, `diff: false`, secrets explicitly supplied and verified; no global `.env`.
- [ ] **Step 5: run available checks.** Build/install collection, ansible-playbook --syntax-check bootstrap/platform/register-app/app, ansible-lint, app render on localhost without VPS mutation. Review and provide evidence with actually available versions.

### Task 3: Legacy replacement, documentation, and integrated verification

**Files:**
- Modify: `README.md`, `Makefile`, `.gitignore`, `docs/{ARCHITECTURE,CICD}.md`
- Remove: `docker-compose.yml`, `.env.example`, old `caddy/`, `volumes/`, `scripts/sync-env-*`, `docs/DATABASE-CONNECTION.md`, old coupled deploy/build workflows.
- Create: `.github/workflows/validate.yml`, `requirements-dev.txt`, `pyproject.toml` and/or needed lint configs, `docs/{APP-CONTRACT,OPERATIONS,MIGRATION}.md`, `scripts/check.sh`, `tests/integration/` if local Docker usable.

**Interfaces:**
- Consumes: Tasks 1 and 2, effective commands and policies.
- Produces: `make setup`, `make check`, `make test`, `make plan`, `make bootstrap`, `make platform`, collection build; CI validation only; complete guide in plain English.

- [ ] **Step 1: remove only replaced legacy.** No historical catalog; CI on push/PR only validates, no VPS secrets. Pin dependencies and Actions to actually verified versions/SHAs.
- [ ] **Step 2: connect docs and real commands.** Example: `make check` runs lint, tests, syntax, and collection build; dangerous commands need explicit target; all illustrated commands must match created code.
- [ ] **Step 3: available local integration.** Local Docker: two apps/previews, third refused, distinct data, effective limits, update and targeted cleanup. Use only marked test resources, without touching existing containers/volumes. If daemon or VM unavailable, keep reproducible opt-in script and report gates not run without claiming real validation.
- [ ] **Step 4: review the whole and run `git diff --check`.** Separate controller tests, Ansible render/syntax, local daemon, Debian 13 VM, and real VPS.

### Task 4: Final review, fixes, and protected local switch

**Files:**
- Modify: only Task 1–3 files to fix reproduced findings.
- External optional: original directory `/Users/nrandriantsarafara/Works/sandbox/vps-services` after private archive and concurrency check; no GitHub or `.git` change.

**Interfaces:**
- Consumes: full uncommitted diff, spec, test evidence, contract and guides.
- Produces: handled findings and honest final state, worktree implementation ready and status distinct from original directory.

- [ ] **Step 1: spec + quality review by a separate agent then final interaction review.** Uncommitted diff packaged including new files; no fake HEAD..HEAD range. Fix verified defects with targeted regression.
- [ ] **Step 2: run affected gates after fixes.** Do not multiply identical suites without new reasons.
- [ ] **Step 3: recheck original directory.** If HEAD/status and files unchanged, prepare a full private archive of the old working tree outside Git (including `.env`), keep `.git` in place then replace only in-scope files with verified new files, without copying cache/.venv/state/secrets. Preserve worktrees and remote. If concurrent work or permissions unresolved, do not force; report exactly what switch remains.
- [ ] **Step 4: report paths and evidence.** No commit/push/PR/deploy. State missing gates, blocked VPS access, and future choice of a real app/domain.
