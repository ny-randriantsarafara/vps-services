# vps-services

IaC for VPS — self-hosted Supabase stack (Postgres, Redis, Auth, Studio, etc.)

## Services

| Service | Profile | Host port (SSH tunnel) |
|---------|---------|----------------------|
| Postgres | always | 5432 |
| Redis | always | 6379 |
| Supabase Studio | supabase | 3000 |
| Supabase API (Kong) | supabase | 8000 |

All ports bind to `127.0.0.1` — not exposed to the internet. Access via SSH tunnel only.

## First-time setup

1. **Clone and configure**
   ```bash
   cp .env.example .env
   # Edit .env with your secrets
   ```

2. **Generate secrets**
   ```bash
   # JWT secret
   openssl rand -base64 32

   # Anon + Service Role keys
   # Use: https://supabase.com/docs/guides/self-hosting/docker#generate-api-keys
   # Paste your JWT_SECRET into the tool
   ```

3. **Start core services**
   ```bash
   make up
   # or: docker compose up -d
   ```

4. **Start full Supabase stack**
   ```bash
   make up-all
   # or: docker compose --profile supabase up -d
   ```

5. **Check status**
   ```bash
   make ps
   ```

## Accessing from your PC (SSH tunnel)

Run `make tunnel` on the VPS to see the exact command, then run it on your PC:

```bash
ssh -L 5432:localhost:5432 \
    -L 6379:localhost:6379 \
    -L 3000:localhost:3000 \
    -L 8000:localhost:8000 \
    user@your-vps -N
```

Or add to `~/.ssh/config`:

```
Host vps
  HostName your-vps-ip
  User your-user
  LocalForward 5432 localhost:5432
  LocalForward 6379 localhost:6379
  LocalForward 3000 localhost:3000
  LocalForward 8000 localhost:8000
```

Then just `ssh vps` keeps all tunnels open.

## Public access (supabase.nyhasinavalona.com)

Supabase Studio and the API are exposed publicly via Caddy at `https://supabase.nyhasinavalona.com`.

**First-time setup:**

1. Ensure DNS is configured: `supabase.nyhasinavalona.com` A record → VPS IP
2. Ensure ports 80 and 443 are open in your VPS firewall
3. Verify Caddy includes `/etc/caddy/conf.d/`:
   ```bash
   grep -r "conf.d" /etc/caddy/Caddyfile
   ```
   If not, either add `import conf.d/*` to your Caddyfile, or copy the config directly into `/etc/caddy/Caddyfile`.
4. Install the config:
   ```bash
   make caddy-install
   ```
   Caddy will automatically provision a Let's Encrypt TLS certificate.

5. Update `.env` on the VPS with production URLs, then restart the Supabase stack:
   ```bash
   # In .env:
   SITE_URL=https://supabase.nyhasinavalona.com
   API_EXTERNAL_URL=https://supabase.nyhasinavalona.com
   SUPABASE_PUBLIC_URL=https://supabase.nyhasinavalona.com
   ```
   ```bash
   make down && make up-all
   ```

**What is exposed:**

| URL | Routes to |
|-----|-----------|
| `https://supabase.nyhasinavalona.com/` | Studio dashboard |
| `https://supabase.nyhasinavalona.com/rest/v1/` | PostgREST API |
| `https://supabase.nyhasinavalona.com/auth/v1/` | GoTrue Auth |
| `https://supabase.nyhasinavalona.com/storage/v1/` | Storage API |
| `https://supabase.nyhasinavalona.com/realtime/v1/` | Realtime (WebSocket) |

**What stays tunnel-only:** Postgres (5432), Redis (6379).

## Connecting other apps to Postgres

From inside the VPS (same Docker network):
```
host: postgres
port: 5432
```

From your PC (via SSH tunnel):
```
host: localhost
port: 5432
```

## Useful commands

```bash
make up          # start core (postgres + redis)
make up-all      # start everything including supabase
make down        # stop all
make logs        # follow logs
make ps          # status
make tunnel      # show ssh tunnel command
```
