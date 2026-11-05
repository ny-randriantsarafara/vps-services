# Operations

All commands run from the repository root, after `make setup`. Those that touch the server require `TARGET=vps-d9d9aca9`.

## 1. Verify the server host key out of band

Inventories require `StrictHostKeyChecking=yes` and the file `inventories/production/known_hosts`. Ansible therefore refuses to connect until the host key has been verified and recorded. Never bypass with `StrictHostKeyChecking=no`.

1. Open the VPS KVM console from the OVH customer area and read the real fingerprint there:

   ```bash
   ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
   ```

2. On the workstation, fetch the key announced by the network and compare the two fingerprints:

   ```bash
   ssh-keyscan -t ed25519 51.210.10.127 > /tmp/vps-host-key
   ssh-keygen -lf /tmp/vps-host-key
   ```

3. Only if they match, record the key in the inventory. A host key is public and may be committed:

   ```bash
   cp /tmp/vps-host-key inventories/production/known_hosts
   ```

Each application repository does the same in `deploy/ansible/known_hosts`. After a VPS reinstall, the fingerprint changes: repeat verification; do not delete the line blindly.

## 2. Initial access

The OVH Debian image provides the `debian` account with `~/.ssh/id_ed25519.pub` injected, but requires a password change that currently blocks SSH. Fix that in the OVH KVM console by logging in with the password received from OVH. No password goes into this repository.

Then set the administrator public keys in `inventories/production/group_vars/all.yml`:

```yaml
vps_admin_public_keys:
  - "ssh-ed25519 AAAA... main-workstation"
```

## 3. Bootstrap

Keep a `debian` session open in another terminal for the whole operation.

```bash
make bootstrap TARGET=vps-d9d9aca9
```

Each step opens its own connection; a failure stops the sequence before any access is removed:

1. As `debian`: verify Debian 13, create `vps-admin` (keys only, sudo validated with `visudo`).
2. As `vps-admin`: independent connection and working `sudo`.
3. SSH hardening: `/etc/ssh/sshd_config.d/10-vps-platform.conf`, validated with `sshd -t` before reload; a rejected file is removed without reload.
4. New `vps-admin` connection after hardening.
5. Remove keys from the `debian` account (`vps_revoke_initial_user_key`).

Then verify from the workstation: `ssh vps-admin@51.210.10.127` works; `ssh root@51.210.10.127` and password authentication are refused.

## 4. OVH recovery

If SSH becomes unreachable:

- **KVM console** (OVH customer area, VPS, KVM): local login, independent of SSH and the firewall. Fix or remove `/etc/ssh/sshd_config.d/10-vps-platform.conf`, then `systemctl reload ssh`; or stop the firewall with `systemctl stop vps-firewall`.
- **Rescue mode**: reboot the VPS in rescue from the customer area, mount the system disk, then fix `authorized_keys`, the SSH drop-in, or disable `vps-firewall.service`. Then reboot to the normal disk.

Automatic OVH backup stays enabled. Do not restore it to fix access: it can reintroduce the old stack. The platform restores no application from that backup.

## 5. Platform

To update only controller code, admission policy and its maintenance/backup timers on an existing host, use `make controller TARGET=vps-d9d9aca9`. It does not reapply SSH, Docker, Caddy installation or firewall provisioning. Refresh ingress after a policy change with `sudo vpsctl ingress refresh`.

```bash
make plan TARGET=vps-d9d9aca9       # --check --diff simulation
make platform TARGET=vps-d9d9aca9
make platform TARGET=vps-d9d9aca9   # second pass: no change expected
```

On a fresh host, `make plan` may flag tasks that depend on packages not yet installed: that is a review aid, not proof.

`platform.yml` installs host, SSH, firewall, Docker, Caddy, and the controller, then reconnects after SSH and firewall changes. It does not start any application.

Checks from **another machine**, IPv4 then IPv6:

```bash
nc -vz 51.210.10.127 22 && nc -vz 51.210.10.127 80 && nc -vz 51.210.10.127 443
nc -vz -w 3 51.210.10.127 5432    # must fail, like any other port
nc -6 -vz 2001:41d0:404:200::74ec 443
nc -6 -vz -w 3 2001:41d0:404:200::74ec 5432
```

To prove `DOCKER-USER` filtering, temporarily publish a test container on a forbidden port, verify it stays unreachable from outside, then remove it. A file check does not replace this test.

## 6. Register an application

Declare accounts in `vps_deploy_accounts`: one nonprod account for previews, a separate account for production.

```yaml
vps_deploy_accounts:
  exemple-nonprod:
    application: exemple
    environments: [preview]
    public_keys: ["ssh-ed25519 AAAA... ci@exemple"]
  exemple-prod:
    application: exemple
    environments: [prod]
    public_keys: ["ssh-ed25519 AAAA... release@exemple"]
```

```bash
make register-app TARGET=vps-d9d9aca9
```

Each account gets its keys and a single sudo rule, `/usr/local/sbin/vpsctl request`, validated with `visudo`. No `docker` group. Policy `/etc/vps-platform/policy.json` is rewritten; no container is started.

## 7. `vpsctl` commands

For a configured backup, `sudo vpsctl backups run --instance vaultwarden-prod` uses the fixed root-owned command in `vps_backup_commands`. It coordinates with delivery through the controller lock. The administrator installs and reviews that command and its private config first. CI cannot install or replace it. The `vps-instance-backup@vaultwarden-prod.timer` unit invokes the same operation every six hours; inspect its result with `systemctl status` and restricted journal output. Removing a backup from inventory does not erase its snapshots; disable its timer explicitly when retiring it.

For administrators only (`vps-admin` and `root`):

```bash
ssh vps-admin@51.210.10.127 sudo vpsctl status
ssh vps-admin@51.210.10.127 sudo vpsctl previews list
ssh vps-admin@51.210.10.127 sudo vpsctl logs --instance exemple-pr-42 --tail 100
ssh vps-admin@51.210.10.127 sudo vpsctl previews renew --instance exemple-pr-42
ssh vps-admin@51.210.10.127 sudo vpsctl previews destroy --instance exemple-pr-42
ssh vps-admin@51.210.10.127 sudo vpsctl cleanup
ssh vps-admin@51.210.10.127 sudo vpsctl cpu-weights refresh
ssh vps-admin@51.210.10.127 sudo vpsctl retire-staging --instance exemple-staging
```

All respond in JSON; exit code 2 for refusal, 1 for failure. `status` lists instances, untracked Docker objects (`untracked_instances`), free space, and `disk_warning` below 15 GiB. `previews destroy` is destructive for that preview’s data only; prod and staging are refused. `cleanup` removes expired or abandoned previews, like the timer.

The `vps-platform-maintenance.timer` runs `status` then `cleanup` every five minutes:

```bash
systemctl list-timers vps-platform-maintenance.timer
journalctl -u vps-platform-maintenance --since today
```

## 8. Audit and state

```bash
sudo tail -n 20 /var/lib/vps-platform/audit.jsonl
sudo cat /var/lib/vps-platform/registry.json
```

Audit holds time, actor, operation, generation, digests, instance, status, and reason; never secrets. The registry has no secrets either. Files `/srv/vps/apps/<application>/<env>/compose.json` do: do not copy them into a ticket or CI.

## 9. Policy

`/etc/vps-platform/policy.json` is generated by Ansible from inventory: `domain` (`vps_domain`), `preview_limit` (`vps_preview_limit`), `maximum_total_memory_mib` (`vps_maximum_total_memory_mib`, 6528 on this VPS; collection default 6144), `accounts` (`vps_deploy_accounts`), `budgets` (`vps_budgets`), `preview_instance_budget` (`vps_preview_instance_budget`), and `administrators`. A manual edit is overwritten on the next `platform` or `register-app`.

Other keys keep controller defaults (`vps_platform/policy.py`):

| Key | Default | Effect |
| --- | --- | --- |
| `preview_ttl_seconds` | 259200 | Preview expiration (72 h) |
| `preparing_lease_seconds` | 900 | Lease for delivery in progress before cleanup |
| `lock_timeout_seconds` | 600 | Maximum lock wait |
| `minimum_free_memory_mib` | 512 | `MemAvailable` margin after a reservation increase |
| `minimum_free_disk_gib` | 10 | Disk reserve; below this, admissions frozen |
| `disk_warning_gib` | 15 | `status` warning threshold |
| `image_growth_reserve_gib` | 2 | Headroom planned for pulls |
| `minimum_free_inode_ratio` | 0.05 | Required free inode ratio |
| `port_start`, `port_end` | 20000, 29999 | Leased loopback ports |

Lowering `vps_preview_limit` below the current preview count blocks creation without removing any. Raising it does not increase CPU, memory, or disk.

## 10. Caddy

- Applications are served on `:443` only. Port 80 stays for Caddy automatic HTTPS: ACME challenges and 308 redirect to HTTPS.
- Instance domain: `apps.nyhasinavalona.com`. Cloudflare DNS carries `*.apps` as A and AAAA to the VPS, **without proxy**: Caddy obtains its own certificate per name on first route load. The wildcard also covers secondary names (`cms.<instance>.apps…`).
- An unknown name gets a neutral 404.
- Administration via `/run/caddy/admin.sock`, unreachable from containers and deploy accounts.
- `vpsctl` writes the full configuration to `/etc/caddy/vps-platform.json` then loads it; a Caddy restart therefore picks up active routes.

```bash
journalctl -u caddy --since "1 hour ago"
sudo cat /etc/caddy/vps-platform.json
```

## 11. Diagnostics

```bash
journalctl -u docker -u caddy -u vps-firewall --since today
sudo iptables -S VPS-INPUT && sudo ip6tables -S VPS-INPUT
sudo iptables -S DOCKER-USER && sudo ip6tables -S DOCKER-USER
sudo docker compose -p vps-exemple-pr-42 ps
sudo docker ps -a --filter label=vps.platform.instance=exemple-pr-42
sudo docker inspect <container>
df -h / && df -i /
```

### Untracked objects or ambiguous registry

A Docker object labeled `vps.platform.*` with no registry entry, or an unreadable registry, blocks admissions (`untracked runtime objects block admission`, `registry unreadable; operator reconciliation required`). To repair:

1. Back up `registry.json` outside the state directory, mode `0600`.
2. Identify the exact scope with `docker ps -a`, `docker volume ls`, and `docker network ls` filtered by `label=vps.platform.instance=<instance>`.
3. Remove only those objects, or fix the registry entry, then run `vpsctl status` again.

Never `docker system prune --volumes` or global deletion: production and staging data would be lost.

### Refresh an onboarding guard

For private application administration, set `vps_instance_private_paths` in administrator inventory, for example `vaultwarden-prod: ["/admin", "/admin/*"]`. Apply the controller policy and refresh ingress. Check both the private path's public 403 and the public application's readiness. An SSH tunnel to the instance loopback port remains available to the administrator; the rule protects Caddy ingress only.

Set `controller_instance_hostnames` and `controller_onboarding_guards` in controller role variables, only from the administrator inventory. Example for one instance:

```yaml
controller_instance_hostnames:
  home-assistant-prod:
    - home-assistant.nyhasinavalona.com
controller_onboarding_guards:
  home-assistant.nyhasinavalona.com:
    path: /api/onboarding
    step: user
```

After the owner is created privately via SSH tunnel, run `sudo vpsctl ingress refresh`. This administrator command takes the registry lock, verifies ownership of existing objects, and republishes ready routes. It does not change generations or start or stop applications. An identical Caddy configuration causes no reload. Maintenance also runs this refresh every five minutes; preview cleanup keeps its existing rules.

A closed guard is exposed as `http_status: protected`, regardless of local health. After full onboarding, Home Assistant no longer serves `/api/onboarding`: its exact 404 `404: Not Found` opens the guard; any other 404 leaves it closed. Onboarding probes target only the registered loopback port, no redirect, with a three-second timeout and a 64 KiB limit. The public path `/api/onboarding/users*` stays forbidden; continue owner creation via the private tunnel after a reset.

Backup processes inherit the active controller lock descriptor. Their direct local commands keep it while they run, so terminating the controller does not release coordination before backup recovery completes. Use signal-aware, bounded backup commands; the Vaultwarden driver restarts its previously running container on ordinary termination. A fatal kill or failed Docker restart needs operator inspection.

A failed delivery with owned runtime resources still needs a fresh backup before a corrected delivery. Only a failed first delivery recorded as never ready, with no owned runtime resources, may retry without a backup. Missing resources after a successful delivery are not treated as an empty first deployment.

## Production/previews rollout and retained staging recovery

1. Capture a private recovery record outside Git: registry, Caddy JSON, both private staging Compose files, exact labeled object/volume inventory, current production health and content summaries. Keep it root-owned `0600`; it contains secrets. Confirm the existing OVH backup. No new daily or weekly backups are scheduled.
2. Validate this checkout with `make check`. Apply the controller/policy, keeping observability disabled, then confirm `vpsctl status`, production routes and Home Assistant/WireGuard connectivity. Existing service memory limits are unchanged. The production envelope including Vaultwarden (5504 MiB) plus one 1024 MiB preview fits the 6528 MiB application ceiling. On 5 November, physical RAM was 7757.9 MiB and available RAM was 5793.4 MiB; 1229.9 MiB stays outside this cap. Measured available RAM, disk and inodes are still independently checked. Additional transition reservations can still refuse a delivery.
3. Run `sudo vpsctl cpu-weights refresh`. It changes Docker CPU shares only, rechecks ownership/effective values and never restarts containers. New normalized Compose enforces 2048 for prod and 512 otherwise; old stored Compose without shares remains accepted by effective-limit validation.
4. After trusted preview/production pipelines are published and verified, explicitly retire only `my-media-staging` and `portfolio-staging`: `sudo vpsctl retire-staging --instance <name>`. This admin-only operation is outside protocol v1. App accounts cannot invoke it. It fences applies, withdraws routes, removes only owned containers/networks, then records `retired`. It never removes named volumes or private Compose. Failure leaves `retiring` with reservations held; inspect privately and retry the same command. A completed retry is idempotent.
5. Confirm retained records and named volumes remain tracked, the staging routes are absent, production health/data remain unchanged, and a trusted preview can use the released compute capacity. Retained disk budgets remain included in admission. Do not manually delete retired registry entries, as their volumes would become untracked.
6. Recovery requires an administrator: keep the volumes and original private Compose in place, confirm no conflicting objects/routes, and reconcile the saved record under the controller lock during a maintenance window before redeploying a newer generation. Restore staging authorization deliberately only if recovery requires it. There is no automatic app-account reopen of retired staging, and no destructive restore/prune command.

The Docker maintenance pins are Engine/CLI 29.9.3, containerd 2.4.2-3 and Compose 5.7.0, verified against the official Debian 13/trixie APT metadata on 2026-11-04. The workstation metadata was newer than the live host cache; both Engine and CLI 29.9.3 were verified in the official index. Package installation can restart Docker: preserve and verify existing WireGuard/firewall hooks first, capture the private recovery record, perform the reviewed upgrade/reboot sequence, then verify all production routes, containers, data summaries, HA entities/devices and WireGuard. Host kernel installation/reboot and live compatibility are deployment checks, not guaranteed by local syntax tests.

See [optional observability](OBSERVABILITY.md) for the independent Alloy rollout and disable/recovery procedure.


Collector-only setup is `make observability TARGET=vps-d9d9aca9`; credentials are validated before collector changes, and this entry point cannot upgrade Docker or Caddy. Enable source-sanitized request logging through the separately reviewed controller installation and `vpsctl ingress refresh`; see [observability](OBSERVABILITY.md). Keep Docker package/kernel maintenance separate.
