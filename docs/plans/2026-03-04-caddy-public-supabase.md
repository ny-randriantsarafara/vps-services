# Caddy Public Access for Supabase — Design

## Context

The existing stack has all ports bound to `127.0.0.1` (SSH tunnel only). The goal is to expose Supabase Studio + API at `https://supabase.nyhasinavalona.com` while keeping Postgres and Redis tunnel-only. Caddy is already installed on the VPS host.

## Decision

- **Approach:** Caddyfile in repo (`caddy/Caddyfile`) + `make caddy-install` target
- **No Docker changes:** Kong (`localhost:8000`) and Studio (`localhost:3000`) are already reachable from the host; Caddy proxies to them directly
- **Postgres and Redis remain tunnel-only** — their `127.0.0.1` bindings are unchanged

## Routing

```
internet → supabase.nyhasinavalona.com (Caddy, HTTPS, auto Let's Encrypt)
    /rest/v1/*      → localhost:8000 (Kong)
    /auth/v1/*      → localhost:8000 (Kong)
    /storage/v1/*   → localhost:8000 (Kong)
    /realtime/v1/*  → localhost:8000 (Kong) — WebSocket passthrough
    /pg/*           → localhost:8000 (Kong)
    /*              → localhost:3000 (Studio)
```

## Files Changed

| File | Change |
|------|--------|
| `caddy/Caddyfile` | New — declarative Caddy config for the subdomain |
| `.env.example` | Update URL defaults to `https://supabase.nyhasinavalona.com` |
| `Makefile` | Add `caddy-install` and `caddy-reload` targets |
| `README.md` | Add "Public access" section |

## Caddyfile

```
supabase.nyhasinavalona.com {
    handle /rest/v1/* { reverse_proxy localhost:8000 }
    handle /auth/v1/* { reverse_proxy localhost:8000 }
    handle /storage/v1/* { reverse_proxy localhost:8000 }
    handle /realtime/v1/* { reverse_proxy localhost:8000 }
    handle /pg/* { reverse_proxy localhost:8000 }
    handle { reverse_proxy localhost:3000 }
}
```

## .env.example URL section (updated)

```
SITE_URL=https://supabase.nyhasinavalona.com
API_EXTERNAL_URL=https://supabase.nyhasinavalona.com
SUPABASE_PUBLIC_URL=https://supabase.nyhasinavalona.com
```

## Makefile targets

```makefile
caddy-install: ## Install Caddy config and reload
    sudo cp caddy/Caddyfile /etc/caddy/conf.d/supabase.caddyfile
    sudo systemctl reload caddy

caddy-reload: ## Reload Caddy after config changes
    sudo systemctl reload caddy
```

## Prerequisites

- DNS: `supabase.nyhasinavalona.com` A record pointing to the VPS IP
- Port 80 and 443 open in VPS firewall (for Caddy + Let's Encrypt)
- Caddy installed with `conf.d` include support (or adapt path to match VPS Caddy config location)
- `.env` on VPS updated with production URLs before restarting the Supabase stack
