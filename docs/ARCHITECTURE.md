# VPS Services — Architecture

## Overview

Self-hosted Supabase stack on a VPS, managed via a single `docker-compose.yml` with Docker profiles. Databases (Postgres, Redis) are accessible only via SSH tunnel. Supabase Studio and API are publicly accessible via Caddy at `https://supabase.nyhasinavalona.com`.

---

## Services

### Core (always running)

| Service | Image | Port | Access |
|---------|-------|------|--------|
| Postgres | `supabase/postgres:15.8.1.060` | `127.0.0.1:5432` | SSH tunnel only |
| Redis | `redis:7-alpine` | `127.0.0.1:6379` | SSH tunnel only |

### Supabase stack (`--profile supabase`)

| Service | Image | Port | Access |
|---------|-------|------|--------|
| Kong (API gateway) | `kong:2.8.1` | `127.0.0.1:8000` | Via Caddy |
| Studio (dashboard) | `supabase/studio:20241202-71911c6` | `127.0.0.1:3000` | Via Caddy |
| Auth (GoTrue) | `supabase/gotrue:v2.158.1` | internal | — |
| REST (PostgREST) | `postgrest/postgrest:v12.2.0` | internal | — |
| Realtime | `supabase/realtime:v2.34.47` | internal | — |
| Storage | `supabase/storage-api:v1.11.13` | internal | — |
| Meta (pg-meta) | `supabase/postgres-meta:v0.84.2` | internal | — |

All services share a single Docker bridge network (`vps-net`).

---

## Access model

```
internet
    └── supabase.nyhasinavalona.com (Caddy, HTTPS + auto Let's Encrypt)
            ├── /rest/v1/*      → Kong :8000
            ├── /auth/v1/*      → Kong :8000
            ├── /storage/v1/*   → Kong :8000
            ├── /realtime/v1/*  → Kong :8000  (WebSocket)
            ├── /pg/*           → Kong :8000
            └── /*              → Studio :3000

developer PC (SSH tunnel)
    ├── localhost:5432  → Postgres
    ├── localhost:6379  → Redis
    ├── localhost:3000  → Studio
    └── localhost:8000  → Kong
```

---

## Key design decisions

**Shared Postgres** — Supabase services and your own apps connect to the same Postgres instance. Supabase uses its own schemas (`auth`, `storage`, `_realtime`, `graphql_public`); your apps use `public`.

**Shared Redis** — Supabase Realtime uses Redis for pub/sub. The same Redis instance is exposed for your other apps via SSH tunnel.

**DB-less Kong** — Kong runs in declarative mode (`KONG_DATABASE=off`), reading all routes and ACL rules from `volumes/kong/kong.yml` at startup. No Kong database needed.

**`wal_level=logical`** — Postgres is started with logical replication enabled so Supabase Realtime can stream row-level changes via the replication protocol.

**Caddy on host (not in Docker)** — Caddy is installed directly on the VPS. Since Docker ports are bound to `127.0.0.1` on the host, Caddy can reach them without any Docker network bridging or port re-binding.

---

## Volumes

| Volume | Used by | Contents |
|--------|---------|----------|
| `postgres-data` | Postgres | Database files |
| `redis-data` | Redis | AOF persistence |
| `storage-data` | Storage | Uploaded files |

---

## File structure

```
vps-services/
  docker-compose.yml      — all services and profiles
  .env                    — secrets (gitignored)
  .env.example            — template committed to git
  Makefile                — convenience targets
  caddy/
    Caddyfile             — public HTTPS routing config
  volumes/
    kong/
      kong.yml            — Kong declarative routes + ACL
  docs/
    ARCHITECTURE.md       — this file
```
