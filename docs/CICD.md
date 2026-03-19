# CI/CD

Deploys automatically on every push to `main`. The workflow validates all configs first, then deploys to the VPS over SSH.

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

## GitHub configuration

### Secrets

Set in: **Settings > Secrets and variables > Actions > Secrets**

| Secret | Value |
|--------|-------|
| `VPS_HOST` | VPS IP or hostname |
| `VPS_USER` | `deploy` |
| `VPS_SSH_KEY` | Contents of `/home/deploy/.ssh/github_actions` (private key) |
| `VPS_HOST_KEY` | Output of `ssh-keyscan -H <vps-host>` from a trusted network |

`VPS_HOST_KEY` is obtained once from a trusted network to prevent MITM on deploys:

```bash
ssh-keyscan -H your-vps-ip-or-hostname
# Copy the full output as the secret value
```

### Repository variables

Set in: **Settings > Secrets and variables > Actions > Variables**

Every key from `.env.example` should exist as a repository variable. This includes `VISA_INSIGHT_APP_DOMAIN` for the Visa Insight public host (must match DNS and `APP_BASE_URL` in the app repo). The deploy workflow assembles the `.env` file on the VPS from all repository variables at deploy time (using `toJSON(vars)`).

To sync variables between your local `.env` and GitHub:

```bash
# Push local .env values to GitHub repository variables
scripts/sync-env-to-gh.sh

# Pull GitHub repository variables to local .env
make sync-env
# or directly:
scripts/sync-env-from-gh.sh
```

---

## What deploys

The workflow rsyncs these files to `/home/deploy/infra/` on the VPS:

- `docker-compose.yml`
- `caddy/Caddyfile`
- `scripts/`
- `volumes/kong/kong.yml`
- `volumes/db/*.sql`
- `volumes/logs/vector.yml`
- `volumes/pooler/pooler.exs`
- `volumes/functions/`
- `Makefile`

It excludes: `.env`, `.env.*`, `.git/`, `docs/`, `*.backup`

The `.env` file is assembled separately from repository variables (never committed to git). The write uses an atomic `tmp + mv` to prevent partial reads.

---

## Deploy pipeline

1. **Validate** — `docker compose config`, `caddy fmt --diff`, `yamllint`
2. **Backup** — copies current `docker-compose.yml`, `Caddyfile`, and `.env` to `.backup` files on the VPS
3. **Rsync** — syncs config files to `/home/deploy/infra/`
4. **Write .env** — assembles `.env` from repository variables via `jq`
5. **Restart** — `docker compose --profile supabase up -d --remove-orphans --pull missing`
6. **Health check** — polls all 14 services (postgres, redis, kong, auth, rest, realtime, storage, imgproxy, meta, functions, studio, analytics, supavisor, caddy) for up to 15 retries at 10s intervals

---

## Troubleshooting

**validate job fails**

| Error | Fix |
|-------|-----|
| `docker compose config` fails | Check `.env.example` — a var without a default may fail dummy .env generation |
| `caddy fmt` fails | Run `caddy fmt --diff caddy/Caddyfile` locally and fix the formatting |
| `yamllint` fails | Fix YAML indentation in `volumes/kong/kong.yml` |

**deploy job fails**

| Error | Fix |
|-------|-----|
| SSH permission denied | Verify `VPS_SSH_KEY` matches `~/.ssh/authorized_keys` on VPS |
| Docker stack unhealthy | SSH to VPS, run `docker compose --profile supabase logs` |
| Health check timeout | Check individual service logs: `docker logs supabase-<service>` |

---

## Visa Insight ingress

Routing lives in `caddy/Caddyfile` with the same path-split pattern as Hoop: `/api/*` → `visa-insight-api:3001`, everything else → `visa-insight-web:3000`. Caddy reads `VISA_INSIGHT_APP_DOMAIN` from the VPS `.env` (set via GitHub **repository variables**). Deploy the Visa Insight compose stack on `vps-net` with service names `visa-insight-api` and `visa-insight-web` before expecting public traffic.

### Post-merge verification (production)

Replace the host with your `VISA_INSIGHT_APP_DOMAIN` value (DNS must point at this VPS):

1. **Web** — `curl -fsS -o /dev/null -w '%{http_code}\n' "https://visa-insight.nyhasinavalona.com/"` (adjust host; expect `200` or your app's normal status).
2. **API** — `curl -fsS "https://visa-insight.nyhasinavalona.com/api/health"` (expect API health payload when the API container is up).

502 on `/api/*` usually means the upstream container is not on `vps-net` or names do not match the Caddyfile.

