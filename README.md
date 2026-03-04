# vps-services

IaC for VPS — self-hosted Supabase stack with Caddy, Postgres, Redis, and full Supabase services.

## Services

| Service | Profile | Access |
|---------|---------|--------|
| Postgres | always | Docker network / Supavisor |
| Redis | always | SSH tunnel (`127.0.0.1:6379`) |
| Caddy | supabase | Public (`80`, `443`) |
| Kong (API gateway) | supabase | Docker internal |
| Studio (dashboard) | supabase | Public via Caddy (basic auth) |
| Supavisor (pooler) | supabase | SSH tunnel (`127.0.0.1:5432`, `127.0.0.1:6543`) |
| Auth, REST, Realtime, Storage, Functions, Meta, Analytics, Vector, imgproxy | supabase | Docker internal |

## First-time setup

1. **Clone and configure**
   ```bash
   cp .env.example .env
   # Edit .env — change ALL default values
   ```

2. **Generate secrets**
   ```bash
   # JWT secret
   openssl rand -base64 32

   # Other secrets (SECRET_KEY_BASE, VAULT_ENC_KEY, PG_META_CRYPTO_KEY, etc.)
   openssl rand -base64 64

   # Anon + Service Role keys
   # Use: https://supabase.com/docs/guides/self-hosting/docker#generate-api-keys
   # Paste your JWT_SECRET into the tool
   ```

3. **Configure DNS**

   Point `supabase.nyhasinavalona.com` (A record) to your VPS IP. Ensure ports 80 and 443 are open in your firewall.

4. **Start core services**
   ```bash
   make up
   # or: docker compose up -d
   ```

5. **Start full Supabase stack**
   ```bash
   make up-all
   # or: docker compose --profile supabase up -d
   ```

6. **Check status**
   ```bash
   make ps
   ```

## Public access (supabase.nyhasinavalona.com)

Caddy runs as a Docker container and automatically provisions TLS certificates via Let's Encrypt. All traffic flows through Kong for routing and authentication.

| URL | Routes to |
|-----|-----------|
| `https://supabase.nyhasinavalona.com/` | Studio dashboard (basic auth) |
| `https://supabase.nyhasinavalona.com/rest/v1/` | PostgREST API |
| `https://supabase.nyhasinavalona.com/auth/v1/` | GoTrue Auth |
| `https://supabase.nyhasinavalona.com/storage/v1/` | Storage API |
| `https://supabase.nyhasinavalona.com/realtime/v1/` | Realtime (WebSocket) |
| `https://supabase.nyhasinavalona.com/graphql/v1` | GraphQL API |
| `https://supabase.nyhasinavalona.com/functions/v1/` | Edge Functions |

## Accessing from your PC (SSH tunnel)

Run `make tunnel` on the VPS to see the exact command, then run it on your PC:

```bash
ssh -L 5432:localhost:5432 \
    -L 6543:localhost:6543 \
    -L 6379:localhost:6379 \
    user@your-vps -N
```

Or add to `~/.ssh/config`:

```
Host vps
  HostName your-vps-ip
  User your-user
  LocalForward 5432 localhost:5432
  LocalForward 6543 localhost:6543
  LocalForward 6379 localhost:6379
```

Then just `ssh vps` keeps all tunnels open.

**What stays tunnel-only:** Postgres (via Supavisor 5432/6543), Redis (6379).

## Connecting other apps to Postgres

From inside the VPS (same Docker network):
```
host: postgres
port: 5432
```

From your PC (via SSH tunnel through Supavisor):
```
host: localhost
port: 5432  (session mode)
port: 6543  (transaction mode)
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
