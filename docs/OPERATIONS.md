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

Declare accounts in `vps_deploy_accounts`: one nonprod account for staging and previews, a separate account for production.

```yaml
vps_deploy_accounts:
  exemple-nonprod:
    application: exemple
    environments: [staging, preview]
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

For administrators only (`vps-admin` and `root`):

```bash
ssh vps-admin@51.210.10.127 sudo vpsctl status
ssh vps-admin@51.210.10.127 sudo vpsctl previews list
ssh vps-admin@51.210.10.127 sudo vpsctl logs --instance exemple-pr-42 --tail 100
ssh vps-admin@51.210.10.127 sudo vpsctl previews renew --instance exemple-pr-42
ssh vps-admin@51.210.10.127 sudo vpsctl previews destroy --instance exemple-pr-42
ssh vps-admin@51.210.10.127 sudo vpsctl cleanup
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

`/etc/vps-platform/policy.json` is generated by Ansible from inventory: `domain` (`vps_domain`), `preview_limit` (`vps_preview_limit`), `accounts` (`vps_deploy_accounts`), `budgets` (`vps_budgets`), `preview_instance_budget` (`vps_preview_instance_budget`), and `administrators`. A manual edit is overwritten on the next `platform` or `register-app`.

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
