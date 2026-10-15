# Migration from the Supabase stack

This repository hosted a shared Supabase stack (Postgres, Redis, Kong, Studio, Supavisor…) behind Caddy, deployed by GitHub Actions on every push to `main`. The VPS was reinstalled on Debian 13: that state is gone and **is not a list of applications to redeploy**.

## What was removed

| Legacy | Replacement |
| --- | --- |
| `docker-compose.yml`, `volumes/`, `caddy/Caddyfile` | Per-application Compose instances, routes validated by `vpsctl` |
| `.env.example`, `scripts/sync-env-*.sh` | Private secrets per instance, supplied by each application |
| `.github/workflows/deploy.yml` (push to `main`) | `validate.yml`, no secrets or deployment |
| Reusable workflows `build-image.yml`, `deploy-compose.yml`, `deploy-service.yml` | `ny.vps.app` role installed at a release SHA |
| `docs/DATABASE-CONNECTION.md`, SSH tunnels to Postgres/Redis | Each application has its own database, isolated per instance |
| Targets `make up`, `up-all`, `tunnel`, `sync-env` | `make setup`, `check`, `plan`, `bootstrap`, `platform`, `register-app` |

No old application is restored, neither from Git nor from the OVH backup.

## Before the first push of this rewrite

Removing files does not neutralize existing callers. Before any push that might trigger a workflow:

1. **Inventory callers** of reusable workflows: search for `ny-randriantsarafara/vps-services/.github/workflows/` in application repositories. A caller pinned to an old SHA keeps working after the rewrite.
2. **Revoke their VPS access**: remove secrets `VPS_HOST`, `VPS_HOST_KEY`, `VPS_SSH_KEY`, and `VPS_USER` from this repository and callers. Do not install the matching public key on the new server, and verify it is not the one OVH injected for the `debian` account.
3. **Check triggers** in GitHub: `deploy.yml` ran on push to `main`. Explicitly disable old workflows if a caller stays active. Do not rely on `chore:` or `[skip ci]`.
4. Plan migration of each application to the contract (see [APP-CONTRACT](APP-CONTRACT.md)), without deploying during this step.

## Original local directory

The checkout `/Users/nrandriantsarafara/Works/sandbox/vps-services` contains an ignored `.env` (old Supabase configuration):

- Before replacement, archive the full old working tree, including `.env`, outside Git with private permissions and a checksum, without printing its contents.
- Keep `.git`, the remote, and worktrees; only replace files in scope.
- The `.env` never enters the new history. A secret still needed is moved back by explicit selection into the private file of the relevant application.

Local rollback: extract the archive into a separate folder, without rerunning its old deploy commands.

## Next steps

1. Fix initial access and verify the host key ([OPERATIONS](OPERATIONS.md), sections 1–3).
2. Validate the platform on a disposable Debian 13 VM: first pass, second pass with no change, reboot, new SSH connections, IPv4/IPv6 ports from another machine.
3. Provision the real VPS after agreement, then measure `df`, idle memory, and network rules; adjust envelopes if needed.
4. Register an explicitly named test application and run a full cycle: two previews, third refused, update, close, expiration.
5. Choose a dedicated domain and TLS mode: `apps.nyhasinavalona.com`, wildcard DNS without proxy, certificates from Caddy (done 11/10/2026).
6. Adopt the contract application by application. Production, off-VPS backups, and restore drills belong to each application.

Server rollback: explicit maintenance of the platform. The OVH backup is kept, but restoring it would reintroduce the old stack.
