# VPS Services rewrite with Ansible

Date: 11 October 2026. Status: **design proposal for review**.

This document defines the future VPS platform and the contract each application repository may use. It is not authorization to implement, delete, publish, or deploy. Examples are illustrative: the future files, roles, and commands described here do not exist yet.

## 1. Expected outcome and confirmed decisions

The `vps-services` repository initializes and configures the server. Each application repository has its Ansible configuration to provision and deploy its application. The platform provides shared tools; it does not contain a manifest that deploys all applications.

Human decisions already taken:

- A non-root administrator account, SSH keys, SSH hardening, a firewall, and Docker form the base.
- Production and staging are two dedicated environments on the same VPS.
- Each PR has its own preview when admission allows.
- The preview cap is **global on the VPS**, initially two and configurable.
- A preview with a database uses its own test data, separate from staging and production.
- The system must stay suited to VPS capacity, simple to understand and debug.
- No old application is restored automatically. Kubernetes and a shared Supabase stack are not required.

The recommended technical choices below, including Compose, role distribution, admission, and automatic lifecycle, still need validation with this specification. Their presence in the document does not make them already approved decisions.

## 2. Starting point and proof limits

The following server and DNS information was verified in the 11 October scoping and passed to this writing. It was not reverified by server connection during writing.

| Item | Transmitted state |
| --- | --- |
| OVH VPS | `vps-d9d9aca9.vps.ovh.net` |
| IPv4 / IPv6 | `51.210.10.127` / `2001:41d0:404:200::74ec` |
| Advertised capacity | 4 vCPU, 8 GiB RAM, 75 GB disk |
| OS | Debian 13 reinstall finished, OVH operation `done`, 100% |
| Initial access | Local public key `~/.ssh/id_ed25519.pub` injected; mandatory initial password change currently blocks SSH with `debian` |
| OVH backup | Automatic enabled, point available from the day before; keep it |
| Portfolio | `nyhasinavalona.com` and `www` on GitHub Pages, HTTP 200 verified after cleanup |
| DNS | Seven old application names removed with authorization; nine entries remain, including email, preserved |

The old server held applications and a Supabase stack, with about 62 GB used of 74. The reinstall erased that state; it is not a list of services to redeploy. Actually available capacity on the new filesystem and idle load remain to be measured.

Current local read: remote repository `https://github.com/ny-randriantsarafara/vps-services`, HEAD `aa5f98ff82f7cab074b2fb0c3381aae4250bb242`. The writing checkout is detached HEAD. No fetch, branch change, or publication was done. Existing files confirm: global Supabase Compose, fixed Caddy routes, and workflow `.github/workflows/deploy.yml` triggered by push to `main`.

The original directory `/Users/nrandriantsarafara/Works/sandbox/vps-services` contains, per scoping inspection, an ignored `.env`. Its private contents were not read. That file must be backed up outside Git before any local replacement. The writing checkout does not contain one: absence here does not excuse protecting the original directory’s copy.

**Proof available at this stage: design and file inspection. No provisioning, idempotence test, deployment, network scan, or restore test on the VPS is validated.**

## 3. Approaches and recommendation

| Approach | Benefit | Cost or limit |
| --- | --- | --- |
| **Ansible + Compose per instance + versioned shared tools** — recommended | Reproducible server, autonomous applications, inspectable files and commands; compatible with a single VPS | Small shared admission and cleanup mechanism to build and verify |
| Host Ansible + Compose scripts copied into each application | Fast first start | Duplicated deployment; global admission easy to bypass or forget; fixes to repeat in each repository |
| Central platform that describes and deploys all applications | Centralized deployment view | Contradicts requested separation; each application delivery depends on the VPS repository |

The recommendation keeps one machine and no cluster orchestrator. The shared mechanism is a short, testable local command, not an HTTP deploy service or a new central database. If that mechanism becomes disproportionate, reduce the application contract rather than build a general platform.

## 4. Repository responsibilities and limits

| Topic | VPS repository | Application repository |
| --- | --- | --- |
| Inventory and access | Server address, verified SSH fingerprints, administrators | Minimal inventory pointing to the same server, authorized deploy user |
| OS, SSH, firewall, Docker | Configures and maintains | Consumes; does not modify the platform |
| Shared HTTP | Installs and configures Caddy; controls allowed domains | Declares routes and HTTP needs of its instances |
| Admission | Sets caps, installs shared controller and local state | Requests a deployment; does not choose its own global quota |
| Images and services | No application image catalog | Dockerfile, external build, images by digest, Compose, health and dependencies |
| Data | Provides isolation, paths, and retention rules | Chooses its database, migrations, test data, backup and restore |
| Secrets | Protects host access and proxy secrets | Owns production, staging, and preview secrets |
| Delivery | Publishes role and shared protocol versions | Chooses a compatible version; triggers its own operations |

A technical list of authorized identities may map an SSH account to an application, environments, and a maximum envelope. It contains no image, stack, or instruction to deploy applications. Adding an identity is an explicit platform operation that starts no application container.

The [glossary](../../../GLOSSARY.md) distinguishes application, service, instance, staging, and preview. No separate ADR is needed before validation: alternatives and rationale are already recorded here.

### Proposed structure, without creating the corresponding files

```text
vps-services/
  inventories/production/        # single VPS; non-secret variables
  playbooks/bootstrap.yml        # initial access and administrator
  playbooks/platform.yml         # platform, no application deployment
  playbooks/register-app.yml      # identity/permissions; no stack
  collections/ansible_collections/ny/vps/
    roles/                       # host, ssh, firewall, docker, ingress, app
    plugins/                     # shared deployment interface
  docs/                          # operations, contract, design
  Makefile                       # fine-grained commands, no hidden action

an-application-repo/
  Dockerfile
  deploy/ansible/deploy.yml
  deploy/ansible/requirements.yml
  deploy/ansible/inventory.yml
  deploy/ansible/environments/    # prod, staging, preview; secrets excluded
  deploy/compose.yml.j2           # services specific to this app
  deploy/data/                   # migrations and fixtures specific to the app
```

### Distribution and versions

Recommendation: a `ny.vps` collection built in this repository. Apps install from Git at an **approved full SHA**, via their `requirements.yml`, targeting the collection subdirectory. Release tags make versions readable; the SHA ensures reproducibility. No dependency on `main`, `latest` download, or manual role copy. Ansible allows a Git collection targeted by subdirectory and commit. [Ansible documentation](https://docs.ansible.com/projects/ansible/latest/collections_guide/collections_installing.html)

The server keeps the protocol number accepted by its shared command; the application collection declares the one it emits. Incompatibility is rejected **before mutation**. A platform update keeps the previous protocol for an explicit migration period; it does not redeploy apps. Ansible, third-party collection, Docker, Compose, and Caddy versions will be pinned and tested together at implementation, without inventing unverified package numbers on Debian 13 here.

## 5. Platform and access without losing SSH

Ansible runs from the workstation or a trusted runner. The server does not need to clone application repositories, host a GitHub runner, or build images.

Provisioning happens in two phases:

1. **Initial access**: human resolution of mandatory password change via the planned OVH channel; verification of the new host fingerprint via an independent channel; `debian` key connection. No secret is requested or read during design.
2. **Permanent access**: create a non-root administrator, proposed name `vps-admin`, install authorized public keys, controlled sudo, successful independent connection with that administrator. Validate `sshd -t`, then apply hardening and repeat a full connection. Keep the initial session and an OVH recovery path until success.

Do not disable the initial account or password access before that test. Target hardening: no SSH root login, key authentication, passwords and interactive authentication disabled after verification, no exotic SSH port to hide the service. Keep console/rescue access as recovery procedure. Firewall changes follow the same order: allow the administration session, apply rules, then test a new connection.

Deploy accounts are separate from the administrator: nonprod access for staging/previews, and a distinct production access per application. They have neither general sudo nor Docker socket access. They may submit a request for their identity and call only the planned shared command. The administrator remains a trusted person who can modify the system; the cap does not claim to resist a root administrator.

Docker Engine and the Compose plugin come from the official APT repository, which supports Debian 13. OS security updates are planned; OS reboots and major Docker changes remain explicit maintenance operations. [Debian installation](https://docs.docker.com/engine/install/debian/)

### Firewall and Docker publishing

Target external policy, IPv4 **and** IPv6: SSH 22, HTTP 80 and HTTPS 443 only; established connections, loopback, and ICMP needed for the network stay allowed. Databases and internal services have no public port.

Recommendation: Docker `iptables` backend, with `iptables-nft` / `ip6tables-nft` tools, host input rules and Docker traffic filtering in `DOCKER-USER`. Keep Docker NAT rules and avoid an untested backend mix. INPUT or UFW alone does not protect ports published by Docker. The forwarding filter must handle the public interface, established connections, and when needed the original destination port before DNAT; it must survive a Docker restart. [Docker firewall](https://docs.docker.com/engine/network/packet-filtering-firewalls/), [iptables chains](https://docs.docker.com/engine/network/firewall-iptables/)

Only Caddy, run on the host via systemd in the recommended approach, listens on 80/443. Apps publish only HTTP upstreams on `127.0.0.1`, on ports assigned by the platform. The shared command refuses `0.0.0.0`, `::`, host network, and any other publishing. Caddy administration uses a Unix socket with restricted permissions, unreachable from containers and application accounts. Access needed for that socket is granted to the shared controller. [Caddy admin options](https://caddyserver.com/docs/caddyfile/options#admin)

Routes are validated data, not arbitrary Caddyfile fragments from apps. The controller assembles configuration from accepted state, validates it, then reloads Caddy under the same lock. An unknown route returns a neutral response; no wildcard sends all requests to a default application. Caddy certificates and configuration stay persistent and protected during preview cleanup.

Validation on VM then VPS must also temporarily publish a forbidden port in a controlled administrator test and verify it is unreachable from another machine. Test IPv4 and IPv6 separately, and the impossibility of reaching a container IP directly from outside. A file check does not replace these tests.

## 6. Instance isolation and HTTP

An instance is identified by `application + environment`, for example `exemple-prod`, `exemple-staging`, `exemple-pr-42`. The application key is unique on the VPS, explicitly registered and tied to the canonical repository. Accepted names are normalized and validated; no PR value becomes a path or shell command directly.

| Resource | Rule |
| --- | --- |
| Compose project | Unique name per instance; no fixed `container_name` |
| Network | Bridge specific to the instance; no application network shared between apps or environments |
| Database/cache | Containers and volumes specific to the instance by default |
| Volumes | Prefixed by project; no shared external volume or mount from another environment |
| Directory | `/srv/vps/apps/<app>/<env>/`; active state controlled by the platform |
| Secrets | Files and credentials distinct per instance; no access to another instance’s secrets |
| HTTP | Validated domain route to a loopback port leased to the instance |

The Caddy-on-host approach avoids one Docker network shared by all apps. Only explicitly declared HTTP services get a loopback port; their databases stay on the instance network. Isolation must be tested, including access to another bridge and host ports from a container. A separate bridge alone does not prove the full network policy.

Application containers have reduced rights: no Docker socket, privileged container, host namespaces, devices, or arbitrary extra capabilities. No access to platform metadata/secrets via a host mount. Allowed mounts are limited to configuration files and instance-owned volumes. Docker shares the VPS kernel: this design suits trusted applications and contributors; it does not promise VM isolation for hostile PRs. Giving access to the Docker daemon is giving powerful control over the host. [Docker security](https://docs.docker.com/engine/security/)

Illustrative domains: `app.apps.example.net`, `app-staging.apps.example.net`, `app-pr-42.apps.example.net`. **None of these domains is configured.** The real domain, its DNS, and TLS mode must be approved separately. Proposal: wildcard A/AAAA on a dedicated subdomain and wildcard certificate via DNS-01, with a Cloudflare token restricted to the zone. That avoids a DNS change on every PR; the certificate stays at platform level. Choosing a wildcard assumes a Caddy build with the right DNS module and verified version. [Caddy HTTPS and DNS challenge](https://caddyserver.com/docs/automatic-https)

Without an approved wildcard, use explicitly authorized records and TLS per name. No removed old name is recreated. Portfolio, `www`, email, and other domains stay outside this rewrite. An HTTP name must belong to the application’s authorized namespace and not overwrite another instance’s route.

Staging and previews: restricted HTTP access proposed by default, no indexing, and test accounts. The exact mechanism — proxy or in-app authentication — will be fixed per app; `robots.txt` alone is not protection. Email, payments, and external integrations use test modes, without production credentials.

## 7. Capacity, caps, and verifiable admission

Two previews form a cap, **not a promise that all applications will fit**. A preview may include several services; it consumes one slot but sums all their needs, databases and migration tasks included.

### Proposed initial envelope

| Global use | Declared max CPU | Declared max RAM |
| --- | --- | --- |
| OS, Docker, Caddy and host margin | 1 vCPU margin | 2 GiB margin |
| Production of all apps | 1.5 vCPU | 3 GiB |
| Staging of all apps | 0.5 vCPU | 1 GiB |
| All previews | 1 vCPU | 2 GiB |
| One preview | At most 0.5 vCPU | At most 1 GiB |

Application categories total at most 3 vCPU / 6 GiB, reserving margin on the advertised VPS. These are configurable admission caps; they do not physically reserve CPU for applications and do not guarantee performance. OS, disk cache, daemon, I/O, and deployment spikes must also be observed. An application that is too heavy is refused or must shrink its stack; it is not admitted on instant low consumption alone.

Each service declares `cpus`, `mem_limit`, `memswap_limit` equal to `mem_limit`, and `pids_limit`. Normalized render is verified and effective values are checked with `docker inspect`. Replicas and temporary jobs count in sums; first proposed version: one replica per service, no blue/green implicitly doubling needs. Direct Compose service limits are preferred over assuming `deploy.resources` application. [Compose reference](https://docs.docker.com/reference/compose-file/services/)

The contract also declares a data growth budget and image download need. Disk proposal in **GiB**, to confirm after `df` on the new install: 18 for all production, 6 for all staging, 5 per preview, 8 for shared images, 8 for OS/configuration/logs, and 10 free reserve. That is a 60 GiB envelope, to compare to actually usable capacity; 75 commercial GB are not 75 GiB.

These disk budgets are **tracked thresholds**, not physical Docker volume quotas. Without a dedicated filesystem and quotas, a database can exceed its budget and fill the disk. The first proposed version limits logs, monitors space, refuses new admissions, and alerts; it does not guarantee hard disk isolation. Quotas or a separate volume would become an explicit project if that guarantee were required.

### Shared control on the VPS

The platform installs a root-owned command, proposed name `vpsctl`, and a root-owned JSON registry in `/var/lib/vps-platform/`. Application Ansible roles send it a structured request. It runs the Compose cycle and HTTP routes; no public API, queue, or extra database is required.

CI accounts are not in the Docker group. Their sudo rule authorizes only that command with a fixed interface; identity and authorized environments are inferred from the effective account, not blindly accepted from the request. The controller takes a private snapshot of input before validation, refuses arbitrary paths, symlinks, and unknown fields, and does not run host shell commands supplied by the app. Normalized Compose is subject to an explicit allow list; `build`, `include`, `extends`, arbitrary bind mounts, and external references do not bypass the contract.

The registry is **operational state**, not a central application manifest. It keeps identity, environment, delivery generation, images/digests, reserved resources, leased ports, timestamps, health, and Docker labels. It does not contain secret values. Private Compose/secret files needed for execution are stored separately with strict permissions.

Admission and mutations are serialized by a VPS-local `flock`. For the first version, the lock covers the whole operation, with a proposed maximum wait of ten minutes; accepting that wait is simpler than handling several simultaneous deployments. Under this lock:

1. Verify identity, protocol, complete input, images by digest, required secrets, paths, and normalized Compose configuration.
2. Reconcile registry and labeled Docker objects; unknown state is reported and blocks ambiguous admissions, with no opportunistic wipe.
3. Count all previews: `preparing`, `running`, `unhealthy`, and `deleting` consume a slot. Production/staging consume none. Updating the same PR does not consume a second slot.
4. Compute the sum of caps after replacing the old reservation with the new one, category and VPS included. Old resources stay counted while they exist; any overlap or extra job must be budgeted.
5. Check available RAM and space/inodes: refuse if the RAM increase does not leave an instant margin of 512 MiB, or if download, initial data, and temp files risk going below 10 GiB free. After pull, measure again before start. If an image size cannot be estimated safely, refuse rather than assume it fits.
6. Reserve slot, budgets, and ports before creation; write state atomically. Create resources, migrate/init if needed, verify health, and publish the route only after success.
7. Write the result and release the lock. On failure, remove only objects created by this operation when safe; otherwise keep state, slot, and diagnostics until reconciliation.

Two concurrent requests from different repositories for the last available slot must produce a single admission. A third preview is refused with a message listing the two occupants, reason, and expiration; **no existing preview is evicted automatically**. No new admission while an incomplete deletion still occupies the slot. The configurable limit lives on the host; an app repository variable cannot raise it.

Lowering `max_active_previews` below the current count blocks creation until release, without deleting previews. Raising that number does not implicitly increase CPU, RAM, or disk. A failure or administrator intervention may require registry repair: that command shows the plan then applies an identified scope, never a global `docker system prune --volumes`.

### Disk and visibility

Proposed Docker rotation: `json-file`, `max-size: "10m"`, `max-file: "3"`; system journal also bounded. Daemon settings apply to new containers, so verify each instance after creation. [Docker rotation](https://docs.docker.com/engine/logging/drivers/json-file/)

A platform timer checks space, inodes, per-instance consumption, and preview state. Proposed warning threshold: less than 15 GiB free; below 10 GiB, admissions frozen. State appears in `vpsctl status`, system journal, and deployment output. An external alert channel remains to be chosen; no third-party notification is configured by this spec. Proposed frequency is five minutes, not a guarantee against massive writes between two measurements. Never delete prod/staging data to make space.

## 8. Application contract and data

Each application provides an Ansible playbook, its environment variables, its Compose template, and its health protocol. It builds images on the workstation or in CI, publishes to the registry, then sends their digests. The platform does not `git pull`, `npm install`, or application build on the VPS.

The shared role `ny.vps.app` has operations `plan`, `apply`, `status`, `logs`, `destroy-preview`. The application provides:

- Registered key, canonical repository, environment `prod`, `staging`, or `preview`, PR number for preview, and delivery generation.
- Immutable images, services and per-service limits; a verifiable resource total, without implicit unlimited cap.
- HTTP routes, internal ports, and readiness test; simple container presence is not success.
- Required secrets and private injection; missing secret = failure before mutation.
- Persistent volumes, disk needs, migrations and data initialization, run in an instance container with limits.
- For prod/staging with durable data: backup/restore procedure and migration compatibility with an image rollback.

Generic formats do not assume Postgres or Supabase. By default, an app with a database deploys a database specific to each instance. An external database would be admitted only with distinct endpoints, credentials, and data demonstrated for each environment; no production database access in preview.

A new preview initializes a fresh volume from synthetic fixtures versioned in the app. An update to that same PR keeps its test data and applies compatible migrations. Proposal: data reset only on explicit app/operator command; not on every push. On definitive preview deletion, its test data is deleted with it. A production backup never serves as the default fixture.

Database credentials are unique per instance, and different from SSH credentials. Nonprod identities have no production privileges. Deleting a PR runs no SQL on staging or prod. The platform does not create a database via a global `supabase-db` container.

### Illustrative example in an application repository

This playbook shows the shape of the proposed interface; it is not runnable before collection creation and validation. `app_image_digest`, `database_image_digest`, `release_generation`, and secrets must be supplied by the delivery context. Fingerprints/digests are not invented in this spec.

```yaml
# deploy/ansible/deploy.yml — fictitious application "exemple"
- name: Deliver an application instance
  hosts: vps
  gather_facts: false
  become: false
  vars_files:
    - "environments/{{ target_environment }}.yml"
  roles:
    - role: ny.vps.app
      vars:
        vps_app:
          protocol: 1
          key: exemple
          repository: organisation/exemple
          environment: "{{ target_environment }}"
          pull_request: "{{ pull_request_number | default(omit) }}"
          generation: "{{ release_generation }}"
          operation: apply
          compose_template: "{{ playbook_dir }}/../compose.yml.j2"
          images:
            web: "{{ app_image_digest }}"
            db: "{{ database_image_digest }}"
            seed: "{{ app_image_digest }}"
          limits: "{{ instance_limits }}"
          storage_budget_gib: "{{ instance_storage_budget_gib }}"
          readiness: {service: web, port: 3000, path: /health/ready}
          secret_file: "{{ lookup('env', 'APP_SECRETS_FILE') }}"
          data:
            mode: "{{ instance_data_policy }}"
            initializer_service: seed
```

For example, the file `environments/preview.yml` declares the profile below. Prod/staging have their own variable files and data policies; they do not inherit fixture initialization.

```yaml
instance_limits:
  web: {cpus: 0.2, memory_mib: 384, pids: 128}
  db: {cpus: 0.2, memory_mib: 384, pids: 128}
  seed: {cpus: 0.1, memory_mib: 128, pids: 64}
instance_storage_budget_gib: 2
instance_data_policy: fixtures_on_first_creation
```

The `seed` job, if needed, must have image, rights, and limits declared in Compose. It runs before the web. For simplicity, admission conservatively sums all declared services, temporary jobs included: here 0.5 vCPU / 896 MiB. This profile respects a preview cap even if services overlap; no extra job can run without declared resources. The role renders Compose locally, sends a request to the controller, and waits for its result; it does not get general sudo. The private secrets file is neither a central manifest nor a committed file.

In `requirements.yml`, the planned source is `vps-services` Git, subdirectory `collections/ansible_collections/ny/vps/`, type `git`, version = full SHA of the chosen release. The exact reference will be written when that release exists. Each application repository picks up collection updates independently.

### Secrets and audit

Value files, private keys, GHCR/DNS tokens, and `.env` stay outside Git. Proposed first local version: private files at `0600` permissions, referenced by path; possible CI: strictly limited GitHub environment secrets. `no_log: true` and `diff: false` on transfer and sensitive tasks. No assembly of all repository variables/secrets without an explicit list.

Credentials generated for an instance are kept on an idempotent rerun; rotation is explicit. Transferred files are installed atomically with `0600` permissions and private directories; temp areas are cleaned even after failure. Normalized Compose configuration containing environment values is a private file and must not be attached to CI logs. Audit records technical actor, instance, digest, generation, admission decision, and result, never secret values.

## 9. Delivery, health, and rollback

A delivery follows: local validation → external build → image publication → admission plan → pull → private preparation → optional migration → Compose → readiness → HTTP route → final HTTP check → status.

`plan` and `--check` reserve no slot; positive admission at plan time may become negative at `apply` time. The final result separately indicates local app health and HTTP/TLS reachability. If domain/TLS is not ready, do not announce the preview publicly available.

For a first instance, the route is added after readiness. For an update, keep the last delivery configuration and bounded diagnostics; interruption is possible with Compose on a single instance. No zero downtime is promised. If readiness fails, roll back to the previous image only when migrations are compatible. Otherwise keep the failure state for intervention, without hiding the problem with automatic data restore.

Production is proposed as manual promotion of a digest validated in staging, with a distinct SSH identity. Migration policy, interruption tolerance, and need for automatic rollback will be decided per application before its first production.

## 10. Previews: proposed lifecycle, to validate

| Event | Proposed behavior |
| --- | --- |
| PR opened / updated | Build without prod secret; create/update request for that PR |
| Two slots occupied | Readable refusal; no eviction or implicit queue; explicit retry after release |
| New push on same PR | Serialized replacement; same volumes; newer generation required |
| Old delivery arriving after a new one | Rejected by monotone generation per instance; digest alone does not define order |
| CI cancel or SSH loss | Controller bounded by timeout; reconciliation before new admission; no slot freed blindly |
| PR closed or merged | Delete only the preview concerned, from its application repository |
| Close during deployment | Serialized delete request, generation tombstone blocking old retry; fresh retry only after explicit reopen |
| Missed CI cleanup | Proposed local expiration after 72 h since last successful deploy or explicit renew |
| `preparing` state after crash | Proposed 15 min lease; reconcile objects before cleanup, without assuming nothing was created |

Production and staging are never affected by the expiration timer. Failed states keep counting while resources remain. A failure does not renew instance TTL. A delete operation removes the route, stops containers, deletes only networks/volumes/secrets marked for that instance, verifies absence, then frees the slot and ports. Labels and registry must be consistent; on ambiguity, the timer alerts without deleting.

Workflows belong to apps. GitHub `concurrency` per app/PR helps order jobs, but does not replace the global VPS lock or generation control. The platform may publish pinned reusable workflows; no logic rebuilds all apps from `vps-services`.

Proposed GitHub automation: staging after validation on the app reference branch, production by manual action, previews on PR events and cleanup on close. These triggers **are not yet approved**. Recommended first version: manual commands of the same contract, then automation after demonstrating the full cycle.

No deploy secrets for PRs from forks. A privileged workflow must not run code from an unapproved PR directly. Playbook/deploy updates must be reviewed before use with a CI key, and prod access stays separate. The local registry can expire a preview without a GitHub token; checking itself whether all PRs are closed would add integration unnecessary for this version.

## 11. Operations and backups

The following commands are proposed future interfaces, **not commands executed or available today**:

```bash
# In the VPS repository: no app started by platform.yml
make plan
ansible-playbook -i inventories/production playbooks/bootstrap.yml
ansible-playbook -i inventories/production playbooks/platform.yml

# In an application repository: explicit environment and identity
ansible-galaxy collection install -r deploy/ansible/requirements.yml
ansible-playbook -i deploy/ansible/inventory.yml deploy/ansible/deploy.yml \
  -e target_environment=preview -e pull_request_number=42 \
  -e release_generation=123 -e @/private/path/images.yml

# Via administrator, read global state
ssh vps-admin@51.210.10.127 sudo vpsctl status
ssh vps-admin@51.210.10.127 sudo vpsctl previews list
ssh vps-admin@51.210.10.127 sudo vpsctl logs --instance exemple-pr-42 --tail 100

# Explicit targeted cleanup, destructive for that preview’s data only
ssh vps-admin@51.210.10.127 sudo vpsctl previews destroy --instance exemple-pr-42
```

The future Makefile exposes operations and parameters, without `up-all` that restores a default stack. Diagnostics include host component `journalctl`, firewall configuration, `docker compose ps`, `docker inspect`, bounded logs per instance, declared/effective resources, and last admission decision. Operator commands use SSH with fingerprint verification; no `StrictHostKeyChecking=no`.

Existing automatic OVH backup stays enabled and its available point is kept. It does not demonstrate coherent restore of an application database. The platform restores no application from that backup.

For an app with durable data, first production requires: chosen off-VPS destination, encryption, distinct backup secrets, coherent export suited to the database, retention, declared temp space, and restore exercise in a test instance. Initial proposal to validate with the app: daily backup, seven dailies and four weeklies, maximum loss target of 24 h and restore in four hours. These targets are not guaranteed until exercise and capacity confirm them. Previews are disposable and not backed up by default.

## 12. Validation before use

No code or test is created at this stage. The following criteria will guide implementation and its proof.

### Local, without VPS

- Ansible/YAML lint and syntax; reproducible collection install from SHAs.
- Compose render without real secrets; schema and limits verified; no floating images or out-of-contract configuration.
- Controller tests: concurrent admission from two apps, counting per PR, aggregate budgets, cap raise/lower, recovery after crash, refusal of dangerous fields and paths.
- Generation tests: old deploy after new, close during apply, duplicate events and repeated delete with no extra effect.
- Secret tests: missing secret refused, private files, no leak in logs and diff output.

### Disposable Debian 13 VM

Use a full VM, not only a container: systemd, SSH, firewall, and Docker must be real. First platform run, second run with no change expected, reboot, new run, new SSH connections. `--check` helps review changes but remains simulation; sensitive tasks must support this mode or explicitly announce verification not performed, with no hidden mutation. [Ansible check mode](https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_checkmode.html)

Integration scenario: a fictitious app with web + database in prod and staging, two previews across two apps, third preview refused. Change a fixture in one preview and verify the other, staging, and prod stay identical. Verify network, volumes, credentials, effective limits, healthcheck, public IPv4/IPv6 ports, and targeted cleanup. After missed close and accelerated test TTL, only the expired preview disappears. Replaying an identical delivery does not regenerate secrets, data, or containers unnecessarily.

### Real VPS, after access is resolved

Measure `df`, idle RAM, versions/cgroups, and network rules; adjust envelopes. Provision only the platform after human validation. Repeat SSH/firewall checks from another machine then a full cycle on an explicitly named test app. Test app backup/restore before any useful data.

Local success is not a validated deployment; an SSH connection is not proof of readiness; local readiness is not proof of DNS/TLS. Each step has its distinct result. Initial access blocked today prevents concluding on all VPS criteria.

## 13. Local replacement and migration, without triggering old CI

Proposed sequence for a later authorized phase:

1. Have this design and its proposed policies validated. No additional VPS reset.
2. Reinspect the original directory: branch, upstream, tracked/untracked changes, ignored files, and remotes. Protect any local work.
3. Back up the original directory and its `.env` in a private archive outside Git, restrictive permissions, with integrity check without displaying contents. Do not rely on stash to save ignored files. Never copy `.env` into the new history.
4. Prepare replacement in a clean adjacent directory. Confirm GitHub choice separately: rewrite of the existing repository recommended to preserve remote and history; a new repository would need an explicit decision. No GitHub repository is deleted.
5. If a branch becomes necessary, use `feat/ansible-vps` from the verified real base, never `codex/`. During implementation, replace old deploy workflows with validation without automatic platform deploy, before any path to publication on `main`.
6. Before later publication, also identify repositories that call old reusable workflows; remove or disable their VPS access and plan their migration, without deploying their apps. A design branch or new repository alone does not neutralize those callers.
7. Do not rely on `chore:` or `[skip ci]` as a safety measure. Concretely verify GitHub triggers and explicitly suspend old deployments with authorization before the first push likely to trigger them. New CI does not provision the VPS on every push.
8. After local validation of the implementation, switch the local directory by controlled rename, keeping the old directory privately recoverable. Replace only secrets still needed, by explicit selection, not the whole old Supabase `.env`.
9. Resolve initial access, provision the platform, and demonstrate idempotence. Then register a fictitious test app to verify the contract; no restore of historical apps.
10. Adopt the contract in each future application repository separately. Production, real domains, and backups need configuration and validation specific to that app.

Local rollback: reopen the saved directory without activating its old deploy commands. Server rollback: explicit platform maintenance, without automatic OVH restore likely to reintroduce the old stack. Do not delete the existing OVH backup.

**This writing executes none of these operations: only this document and the glossary are added.**

## 14. Points to present for final validation

| Proposal | Material decision expected |
| --- | --- |
| Ansible + Compose, pinned Git collection, local shared controller | Validate this reuse level and the cost of global control |
| Caddy on host, loopback upstreams per instance | Validate HTTP strategy; name dedicated domain and TLS mode later |
| Envelopes 3 vCPU / 6 GiB for apps, preview ≤ 0.5 vCPU / 1 GiB | Validate starting caps, recalibrate after measurement; accept refusals if an app is too heavy |
| Monitored disk, no hard quotas | Accept this limit or request a separate quotas project |
| Third preview refusal, 72 h TTL, data deletion on expiration/close | Validate refusal, retention, and automatic preview deletion |
| PR update keeping its test data | Validate this behavior rather than reset on every push |
| First manual version, then automatic staging, manual prod | Validate GitHub trigger policy, without confusing it with authorization to deploy now |
| Rewrite of existing GitHub repository, private archive of original directory | Confirm during migration the fate of the repository and neutralization of old CI |

The global cap of two previews, repository separation, dedicated prod/staging, and isolated test data are already confirmed. The rows above specify their proposed implementation; they do not open a new questionnaire in this document.
