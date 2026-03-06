# VPS Services — Architecture

## Overview

Self-hosted Supabase stack on a VPS, managed via a single `docker-compose.yml` with Docker profiles. All services run in Docker containers on a shared bridge network (`vps-net`). Public access is provided by a Caddy reverse proxy container with automatic TLS. Database access is tunneled via SSH.

---

## Services

### Core (always running)

| Service  | Image                          | Port             | Access                     |
| -------- | ------------------------------ | ---------------- | -------------------------- |
| Postgres | `supabase/postgres:15.8.1.085` | internal only    | Docker network / Supavisor |
| Redis    | `redis:7-alpine`               | `127.0.0.1:6379` | SSH tunnel only            |

### Supabase stack (`--profile supabase`)

| Service              | Image                            | Port                               | Access                |
| -------------------- | -------------------------------- | ---------------------------------- | --------------------- |
| Caddy                | `caddy:2-alpine`                 | `80`, `443`                        | Public (internet)     |
| Kong (API gateway)   | `kong:2.8.1`                     | internal only                      | Via Caddy             |
| Studio (dashboard)   | `supabase/studio:2026.02.16`     | internal only                      | Via Kong (basic auth) |
| Auth (GoTrue)        | `supabase/gotrue:v2.186.0`       | internal only                      | Via Kong              |
| REST (PostgREST)     | `postgrest/postgrest:v14.5`      | internal only                      | Via Kong              |
| Realtime             | `supabase/realtime:v2.76.5`      | internal only                      | Via Kong (WebSocket)  |
| Storage              | `supabase/storage-api:v1.37.8`   | internal only                      | Via Kong              |
| imgproxy             | `darthsim/imgproxy:v3.30.1`      | internal only                      | Via Storage           |
| Edge Functions       | `supabase/edge-runtime:v1.70.3`  | internal only                      | Via Kong              |
| Meta (pg-meta)       | `supabase/postgres-meta:v0.95.2` | internal only                      | Via Kong              |
| Analytics (Logflare) | `supabase/logflare:1.31.2`       | internal only                      | Studio                |
| Vector               | `timberio/vector:0.53.0-alpine`  | internal only                      | Log pipeline          |
| Supavisor (pooler)   | `supabase/supavisor:2.7.4`       | `127.0.0.1:5432`, `127.0.0.1:6543` | SSH tunnel            |

---

## Access model

```
internet
    ├── supabase.nyhasinavalona.com (Caddy, HTTPS + auto Let's Encrypt)
    │       └── Kong :8000 (Docker internal)
                    ├── /rest/v1/*        → PostgREST (API key auth)
                    ├── /auth/v1/*        → GoTrue (API key auth)
                    ├── /storage/v1/*     → Storage (self-managed auth)
                    ├── /realtime/v1/*    → Realtime WebSocket (API key auth)
                    ├── /graphql/v1       → PostgREST GraphQL (API key auth)
                    ├── /functions/v1/*   → Edge Functions
                    ├── /pg/*             → postgres-meta (admin only)
                    └── /*                → Studio (basic auth)
    ├── pomodoro.nyhasinavalona.com
    │       └── pomodoro:3000 (Docker internal)
    ├── hoop.nyhasinavalona.com
    │       ├── /api/* -> hoop-api:3001 (Docker internal)
    │       └── /*     -> hoop-web:3000 (Docker internal)

developer PC (SSH tunnel)
    ├── localhost:5432  → Supavisor (session mode pooling)
    ├── localhost:6543  → Supavisor (transaction mode pooling)
    └── localhost:6379  → Redis

other Docker apps (same vps-net)
    └── postgres:5432   → direct Postgres connection
```

---

## Key design decisions

**Shared Postgres** — Supabase services and your own apps connect to the same Postgres instance. Supabase uses its own schemas (`auth`, `storage`, `_realtime`, `graphql_public`); your apps use `public`. The Supabase Postgres image includes all required roles and extensions.

**Supavisor connection pooler** — External Postgres access goes through Supavisor rather than connecting directly. Port 5432 provides session-mode pooling, port 6543 provides transaction-mode pooling. Other Docker services on `vps-net` connect directly to `postgres:5432`.

**Shared Redis** — Redis is a core service available for your apps via SSH tunnel. Supabase Realtime no longer requires Redis.

**DB-less Kong** — Kong runs in declarative mode (`KONG_DATABASE=off`), reading all routes and ACL rules from `volumes/kong/kong.yml` at startup. The entrypoint evaluates environment variables into the config template.

**`log_min_messages=fatal`** — Postgres suppresses verbose log messages to prevent Realtime polling queries from flooding logs.

**Caddy in Docker** — Caddy runs as a container on the same Docker network, binding host ports 80 and 443. It proxies all traffic to Kong, which handles internal routing and authentication. TLS certificates are automatically provisioned via Let's Encrypt and persisted in a named volume.

**Vector + Logflare** — Container logs are collected by Vector (via Docker socket), parsed per service, and shipped to Logflare (analytics). Studio uses Logflare for the log viewer.

---

## Volumes

| Volume          | Used by           | Contents                |
| --------------- | ----------------- | ----------------------- |
| `postgres-data` | Postgres          | Database files          |
| `redis-data`    | Redis             | AOF persistence         |
| `storage-data`  | Storage, imgproxy | Uploaded files          |
| `db-config`     | Postgres          | pgsodium decryption key |
| `deno-cache`    | Edge Functions    | Deno module cache       |
| `caddy_data`    | Caddy             | TLS certificates        |
| `caddy_config`  | Caddy             | Caddy runtime config    |

---

## File structure

```
vps-services/
  docker-compose.yml          — all services and profiles
  .env                        — secrets (gitignored)
  .env.example                — template committed to git
  Makefile                    — convenience targets
  caddy/
    Caddyfile                 — Caddy reverse proxy config
  scripts/
    sync-env-from-gh.sh       — pull GitHub repo variables to local .env
    sync-env-to-gh.sh         — push local .env to GitHub repo variables
  volumes/
    kong/
      kong.yml                — Kong declarative routes + ACL
    db/
      _supabase.sql           — create _supabase database
      logs.sql                — create _analytics schema
      pooler.sql              — create _supavisor schema
      realtime.sql            — create _realtime schema
      webhooks.sql            — pg_net extension + hooks
      roles.sql               — set Supabase role passwords
      jwt.sql                 — set JWT app settings
    logs/
      vector.yml              — Vector log pipeline config
    pooler/
      pooler.exs              — Supavisor tenant config
    functions/
      main/index.ts           — Edge Functions entrypoint
      hello/index.ts          — example function
  .github/
    workflows/
      deploy.yml              — CI/CD: validate + deploy to VPS
  docs/
    ARCHITECTURE.md           — this file
    CICD.md                   — CI/CD setup and troubleshooting
```
