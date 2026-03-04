# CI/CD

Deploys automatically on every push to `main`. The workflow validates all configs first, then deploys to the VPS over SSH. A rollback runs automatically if services fail health checks after deploy.

Workflow file: `.github/workflows/deploy.yml`

---

## One-time VPS setup

Run as root on the VPS once. Never again.

```bash
# Create deploy user
useradd -m -s /bin/bash deploy
usermod -aG docker deploy

# Create deploy directory
mkdir -p /home/deploy/infra/caddy
mkdir -p /home/deploy/infra/volumes
chown -R deploy:deploy /home/deploy/infra

# Generate SSH keypair for GitHub Actions
sudo -u deploy ssh-keygen -t ed25519 -C "github-actions-deploy" \
  -f /home/deploy/.ssh/github_actions -N ""
cat /home/deploy/.ssh/github_actions.pub >> /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys

# Print private key — paste into GitHub secret VPS_SSH_KEY
cat /home/deploy/.ssh/github_actions
```

---

## GitHub secrets

Set in: **Settings > Secrets and variables > Actions**

| Secret | Value |
|--------|-------|
| `VPS_HOST` | VPS IP or hostname |
| `VPS_USER` | `deploy` |
| `VPS_SSH_KEY` | Contents of `/home/deploy/.ssh/github_actions` (private key) |
| `VPS_HOST_KEY` | Output of `ssh-keyscan -H <vps-host>` from a trusted network |
| `VPS_ENV` | Full contents of the production `.env` file |

`VPS_HOST_KEY` is obtained once from a trusted network to prevent MITM on deploys:

```bash
ssh-keyscan -H your-vps-ip-or-hostname
# Copy the full output as the secret value
```

---

## What deploys

The workflow rsyncs these files to `/home/deploy/infra/` on the VPS:

- `docker-compose.yml`
- `caddy/Caddyfile`
- `volumes/kong/kong.yml`
- `volumes/db/*.sql`
- `volumes/logs/vector.yml`
- `volumes/pooler/pooler.exs`
- `volumes/functions/`
- `Makefile`

It excludes: `.env`, `.git/`, `docs/`, `*.backup`

The `.env` file is written separately from the `VPS_ENV` secret (never committed to git).

---

## Troubleshooting

**validate job fails**

| Error | Fix |
|-------|-----|
| `docker compose config` fails | Check `.env.example` — a var without a default may fail dummy .env generation |
| `caddy fmt` fails | Run `caddy fmt --diff caddy/Caddyfile` locally and fix the formatting |
| `yamllint` fails | Fix YAML indentation in `volumes/kong/kong.yml` |
| VPS_ENV key check fails | Add the missing key to the `VPS_ENV` GitHub secret |

**deploy job fails**

| Error | Fix |
|-------|-----|
| SSH permission denied | Verify `VPS_SSH_KEY` matches `~/.ssh/authorized_keys` on VPS |
| Docker stack unhealthy | SSH to VPS, run `docker compose --profile supabase logs` |
| Rollback triggered | Check previous `.backup` files and workflow logs for root cause |
