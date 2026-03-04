# VPS Services IaC Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stand up a full self-hosted Supabase stack + standalone Redis on a VPS using a single `docker-compose.yml` with profiles, all ports bound to `127.0.0.1` for SSH-tunnel-only access.

**Architecture:** Single `docker-compose.yml` with two tiers — core services (Postgres + Redis, no profile) that always run, and Supabase services (Kong, Auth, REST, Realtime, Storage, Meta, Studio) under the `supabase` profile. Postgres is shared: Supabase connects to it internally AND other apps can connect via SSH tunnel. One Redis instance serves both Supabase Realtime and other apps.

**Tech Stack:** Docker Compose v2, supabase/postgres:15, redis:7-alpine, Kong 2.8 (DB-less), supabase/gotrue, postgrest/postgrest, supabase/realtime, supabase/storage-api, supabase/postgres-meta, supabase/studio

---

## Task 1: Project scaffold + .gitignore

**Files:**
- Create: `.gitignore`
- Create: `docs/plans/2026-03-04-vps-services-iac.md` (this file)

**Step 1: Create .gitignore**

```
# Secrets
.env

# Docker local data
volumes/db/data/
volumes/storage/

# OS
.DS_Store
Thumbs.db
```

**Step 2: Commit**

```bash
git add .gitignore docs/
git commit -m "chore: init project scaffold and plan"
```

---

## Task 2: Create .env.example

**Files:**
- Create: `.env.example`

**Step 1: Write .env.example**

```bash
############################################
# Postgres
############################################
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=change-me-strong-password

############################################
# Redis
############################################
REDIS_PORT=6379

############################################
# Supabase JWT (generate with: openssl rand -base64 32)
# Anon/Service keys: https://supabase.com/docs/guides/self-hosting/docker#generate-api-keys
############################################
JWT_SECRET=change-me-super-secret-jwt-token-with-at-least-32-chars
ANON_KEY=
SERVICE_ROLE_KEY=

############################################
# Supabase Dashboard auth
############################################
DASHBOARD_USERNAME=supabase
DASHBOARD_PASSWORD=change-me-dashboard-password

############################################
# URLs (use localhost for SSH tunnel access)
############################################
SITE_URL=http://localhost:3000
API_EXTERNAL_URL=http://localhost:8000
SUPABASE_PUBLIC_URL=http://localhost:8000

############################################
# Kong ports
############################################
KONG_HTTP_PORT=8000
KONG_HTTPS_PORT=8443

############################################
# Studio port
############################################
STUDIO_PORT=3000

############################################
# Auth (GoTrue)
############################################
GOTRUE_MAILER_AUTOCONFIRM=true
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_SENDER_NAME=Supabase
SMTP_ADMIN_EMAIL=admin@example.com

############################################
# Storage
############################################
STORAGE_BACKEND=file
FILE_SIZE_LIMIT=52428800
```

**Step 2: Copy to .env and fill in secrets**

```bash
cp .env.example .env
# Edit .env with real values — never commit .env
```

**Step 3: Generate JWT_SECRET**

```bash
openssl rand -base64 32
```

For ANON_KEY and SERVICE_ROLE_KEY, use the Supabase key generator:
https://supabase.com/docs/guides/self-hosting/docker#generate-api-keys
(paste your JWT_SECRET into the tool)

**Step 4: Commit**

```bash
git add .env.example
git commit -m "chore: add .env.example with all required variables"
```

---

## Task 3: Create Kong declarative config

**Files:**
- Create: `volumes/kong/kong.yml`

Kong runs in DB-less mode. This file defines all API routes that proxy to internal Supabase services.

**Step 1: Create directory**

```bash
mkdir -p volumes/kong
```

**Step 2: Write volumes/kong/kong.yml**

```yaml
_format_version: "1.1"

###
### Consumers / Users
###
consumers:
  - username: anon
    keyauth_credentials:
      - key: ${SUPABASE_ANON_KEY}
  - username: service_role
    keyauth_credentials:
      - key: ${SUPABASE_SERVICE_KEY}

###
### Access Control List
###
acls:
  - consumer: anon
    group: anon
  - consumer: service_role
    group: admin

###
### API Routes
###
services:
  ## Open Auth routes
  - name: auth-v1-open
    url: http://auth:9999/verify
    routes:
      - name: auth-v1-open
        strip_path: true
        paths:
          - /auth/v1/verify
    plugins:
      - name: cors
  - name: auth-v1-open-callback
    url: http://auth:9999/callback
    routes:
      - name: auth-v1-open-callback
        strip_path: true
        paths:
          - /auth/v1/callback
    plugins:
      - name: cors
  - name: auth-v1-open-meta
    url: http://auth:9999/
    routes:
      - name: auth-v1-open-meta
        strip_path: true
        paths:
          - /auth/v1/
    plugins:
      - name: cors
      - name: key-auth
        config:
          hide_credentials: false
      - name: acl
        config:
          hide_groups_header: true
          allow:
            - anon
            - admin

  ## Protected Auth routes
  - name: auth-v1
    _comment: "GoTrue: /auth/v1/* -> http://auth:9999/*"
    url: http://auth:9999/
    routes:
      - name: auth-v1-all
        strip_path: true
        paths:
          - /auth/v1/
    plugins:
      - name: cors
      - name: key-auth
        config:
          hide_credentials: false
      - name: acl
        config:
          hide_groups_header: true
          allow:
            - anon
            - admin

  ## REST API
  - name: rest-v1
    _comment: "PostgREST: /rest/v1/* -> http://rest:3000/*"
    url: http://rest:3000/
    routes:
      - name: rest-v1-all
        strip_path: true
        paths:
          - /rest/v1/
    plugins:
      - name: cors
      - name: key-auth
        config:
          hide_credentials: true
      - name: acl
        config:
          hide_groups_header: true
          allow:
            - anon
            - admin

  ## Realtime
  - name: realtime-v1
    _comment: "Realtime: /realtime/v1/* -> http://realtime:4000/socket/*"
    url: http://realtime:4000/socket/
    routes:
      - name: realtime-v1-all
        strip_path: true
        paths:
          - /realtime/v1/
    plugins:
      - name: cors
      - name: key-auth
        config:
          hide_credentials: false
      - name: acl
        config:
          hide_groups_header: true
          allow:
            - anon
            - admin

  ## Storage
  - name: storage-v1
    _comment: "Storage: /storage/v1/* -> http://storage:5000/*"
    url: http://storage:5000/
    routes:
      - name: storage-v1-all
        strip_path: true
        paths:
          - /storage/v1/
    plugins:
      - name: cors
      - name: key-auth
        config:
          hide_credentials: false
      - name: acl
        config:
          hide_groups_header: true
          allow:
            - anon
            - admin

  ## Postgres Meta
  - name: meta
    _comment: "pg-meta: /pg/* -> http://meta:8080/*"
    url: http://meta:8080/
    routes:
      - name: meta-all
        strip_path: true
        paths:
          - /pg/
    plugins:
      - name: key-auth
        config:
          hide_credentials: false
      - name: acl
        config:
          hide_groups_header: true
          allow:
            - admin
```

**Step 3: Commit**

```bash
git add volumes/kong/kong.yml
git commit -m "chore: add Kong declarative routing config"
```

---

## Task 4: Create docker-compose.yml — core services

**Files:**
- Create: `docker-compose.yml`

**Step 1: Write docker-compose.yml with postgres + redis only**

```yaml
name: vps-services

volumes:
  postgres-data:
  redis-data:
  storage-data:

networks:
  vps-net:
    driver: bridge

services:

  ############################################################
  # CORE — always running (no profile)
  ############################################################

  postgres:
    image: supabase/postgres:15.8.1.060
    restart: unless-stopped
    ports:
      - "127.0.0.1:${POSTGRES_PORT:-5432}:5432"
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB:-postgres}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - vps-net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-postgres}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    command: >
      postgres
        -c wal_level=logical
        -c max_replication_slots=5
        -c max_wal_senders=5

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    ports:
      - "127.0.0.1:${REDIS_PORT:-6379}:6379"
    volumes:
      - redis-data:/data
    networks:
      - vps-net
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    command: redis-server --appendonly yes
```

Note on `wal_level=logical`: Supabase Realtime requires logical replication to stream DB changes. This is the only Postgres config customization needed.

**Step 2: Validate**

```bash
docker compose config
```

Expected: No errors, merged config printed to stdout.

**Step 3: Test core startup**

```bash
docker compose up -d
docker compose ps
```

Expected: Both `postgres` and `redis` show `healthy` status.

**Step 4: Verify Postgres is reachable**

```bash
docker compose exec postgres psql -U postgres -c '\l'
```

Expected: List of databases including `postgres`.

**Step 5: Verify Redis is reachable**

```bash
docker compose exec redis redis-cli ping
```

Expected: `PONG`

**Step 6: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add core postgres and redis services"
```

---

## Task 5: Add Supabase services to docker-compose.yml

**Files:**
- Modify: `docker-compose.yml` (append to services section)

Append the following services inside the `services:` block. All have `profiles: [supabase]`.

**Step 1: Append Supabase services**

```yaml
  ############################################################
  # SUPABASE — start with: docker compose --profile supabase up -d
  ############################################################

  kong:
    image: kong:2.8.1
    restart: unless-stopped
    profiles: [supabase]
    ports:
      - "127.0.0.1:${KONG_HTTP_PORT:-8000}:8000"
      - "127.0.0.1:${KONG_HTTPS_PORT:-8443}:8443"
    environment:
      KONG_DATABASE: "off"
      KONG_DECLARATIVE_CONFIG: /var/lib/kong/kong.yml
      KONG_DNS_ORDER: LAST,A,CNAME
      KONG_PLUGINS: request-transformer,cors,key-auth,acl,basic-auth
      KONG_NGINX_PROXY_PROXY_BUFFER_SIZE: 160k
      KONG_NGINX_PROXY_PROXY_BUFFERS: "64 160k"
      SUPABASE_ANON_KEY: ${ANON_KEY}
      SUPABASE_SERVICE_KEY: ${SERVICE_ROLE_KEY}
    volumes:
      - ./volumes/kong/kong.yml:/var/lib/kong/kong.yml:ro
    networks:
      - vps-net
    depends_on:
      - auth
      - rest

  auth:
    image: supabase/gotrue:v2.158.1
    restart: unless-stopped
    profiles: [supabase]
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      GOTRUE_API_HOST: 0.0.0.0
      GOTRUE_API_PORT: 9999
      API_EXTERNAL_URL: ${API_EXTERNAL_URL:-http://localhost:8000}
      GOTRUE_DB_DRIVER: postgres
      GOTRUE_DB_DATABASE_URL: postgres://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-postgres}?search_path=auth
      GOTRUE_SITE_URL: ${SITE_URL:-http://localhost:3000}
      GOTRUE_URI_ALLOW_LIST: "*"
      GOTRUE_DISABLE_SIGNUP: "false"
      GOTRUE_JWT_ADMIN_ROLES: service_role
      GOTRUE_JWT_AUD: authenticated
      GOTRUE_JWT_DEFAULT_GROUP_NAME: authenticated
      GOTRUE_JWT_EXP: 3600
      GOTRUE_JWT_SECRET: ${JWT_SECRET}
      GOTRUE_MAILER_AUTOCONFIRM: ${GOTRUE_MAILER_AUTOCONFIRM:-true}
      GOTRUE_SMTP_ADMIN_EMAIL: ${SMTP_ADMIN_EMAIL:-admin@example.com}
      GOTRUE_SMTP_HOST: ${SMTP_HOST:-}
      GOTRUE_SMTP_PORT: ${SMTP_PORT:-587}
      GOTRUE_SMTP_USER: ${SMTP_USER:-}
      GOTRUE_SMTP_PASS: ${SMTP_PASS:-}
      GOTRUE_SMTP_SENDER_NAME: ${SMTP_SENDER_NAME:-Supabase}
      GOTRUE_MAILER_URLPATHS_INVITE: ${API_EXTERNAL_URL:-http://localhost:8000}/auth/v1/verify
      GOTRUE_MAILER_URLPATHS_CONFIRMATION: ${API_EXTERNAL_URL:-http://localhost:8000}/auth/v1/verify
      GOTRUE_MAILER_URLPATHS_RECOVERY: ${API_EXTERNAL_URL:-http://localhost:8000}/auth/v1/verify
      GOTRUE_MAILER_URLPATHS_EMAIL_CHANGE: ${API_EXTERNAL_URL:-http://localhost:8000}/auth/v1/verify
    networks:
      - vps-net

  rest:
    image: postgrest/postgrest:v12.2.0
    restart: unless-stopped
    profiles: [supabase]
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      PGRST_DB_URI: postgres://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-postgres}
      PGRST_DB_SCHEMAS: public,storage,graphql_public
      PGRST_DB_ANON_ROLE: anon
      PGRST_JWT_SECRET: ${JWT_SECRET}
      PGRST_DB_USE_LEGACY_GUCS: "false"
      PGRST_APP_SETTINGS_JWT_SECRET: ${JWT_SECRET}
      PGRST_APP_SETTINGS_JWT_EXP: 3600
    networks:
      - vps-net
    command: postgrest

  realtime:
    image: supabase/realtime:v2.34.47
    restart: unless-stopped
    profiles: [supabase]
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      PORT: 4000
      DB_HOST: postgres
      DB_PORT: 5432
      DB_USER: ${POSTGRES_USER:-postgres}
      DB_PASSWORD: ${POSTGRES_PASSWORD}
      DB_NAME: ${POSTGRES_DB:-postgres}
      DB_AFTER_CONNECT_QUERY: "SET search_path TO _realtime"
      DB_ENC_KEY: supabaserealtime
      API_JWT_SECRET: ${JWT_SECRET}
      FLY_ALLOC_ID: fly123
      FLY_APP_NAME: realtime
      SECRET_KEY_BASE: UpNVntn3cDxHJpq99YMc1T1AQgQpc8kfYTuRgBiYa15BLrx8etQoXz3gZv1/u2oq
      ERL_AFLAGS: -proto_dist inet_tcp
      ENABLE_TAILSCALE: "false"
      DNS_NODES: "''"
      REDIS_URL: redis://redis:6379
    networks:
      - vps-net
    command: >
      sh -c "/app/bin/migrate && /app/bin/realtime eval 'Realtime.Release.seeds(Realtime.Repo)' && /app/bin/server"

  storage:
    image: supabase/storage-api:v1.11.13
    restart: unless-stopped
    profiles: [supabase]
    depends_on:
      postgres:
        condition: service_healthy
      rest:
        condition: service_started
    environment:
      ANON_KEY: ${ANON_KEY}
      SERVICE_KEY: ${SERVICE_ROLE_KEY}
      POSTGREST_URL: http://rest:3000
      PGRST_JWT_SECRET: ${JWT_SECRET}
      DATABASE_URL: postgres://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-postgres}
      FILE_SIZE_LIMIT: ${FILE_SIZE_LIMIT:-52428800}
      STORAGE_BACKEND: ${STORAGE_BACKEND:-file}
      FILE_STORAGE_BACKEND_PATH: /var/lib/storage
      TENANT_ID: stub
      REGION: stub
      GLOBAL_S3_BUCKET: stub
      ENABLE_IMAGE_TRANSFORMATION: "true"
      IMGPROXY_URL: http://imgproxy:5001
    volumes:
      - storage-data:/var/lib/storage
    networks:
      - vps-net

  meta:
    image: supabase/postgres-meta:v0.84.2
    restart: unless-stopped
    profiles: [supabase]
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      PG_META_PORT: 8080
      PG_META_DB_HOST: postgres
      PG_META_DB_PORT: 5432
      PG_META_DB_NAME: ${POSTGRES_DB:-postgres}
      PG_META_DB_USER: ${POSTGRES_USER:-postgres}
      PG_META_DB_PASSWORD: ${POSTGRES_PASSWORD}
    networks:
      - vps-net

  studio:
    image: supabase/studio:20241202-71911c6
    restart: unless-stopped
    profiles: [supabase]
    ports:
      - "127.0.0.1:${STUDIO_PORT:-3000}:3000"
    depends_on:
      - auth
      - rest
      - meta
    environment:
      STUDIO_PG_META_URL: http://meta:8080
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      DEFAULT_ORGANIZATION_NAME: "My Org"
      DEFAULT_PROJECT_NAME: "VPS Services"
      SUPABASE_URL: http://kong:8000
      SUPABASE_PUBLIC_URL: ${SUPABASE_PUBLIC_URL:-http://localhost:8000}
      SUPABASE_ANON_KEY: ${ANON_KEY}
      SUPABASE_SERVICE_KEY: ${SERVICE_ROLE_KEY}
      AUTH_JWT_SECRET: ${JWT_SECRET}
      LOGFLARE_API_KEY: ""
      LOGFLARE_URL: http://analytics:4000
      NEXT_PUBLIC_ENABLE_LOGS: "true"
      NEXT_ANALYTICS_BACKEND_PROVIDER: postgres
    networks:
      - vps-net
    healthcheck:
      test: ["CMD", "node", "-e", "require('http').get('http://localhost:3000/api/profile', (r) => {process.exit(r.statusCode === 200 ? 0 : 1)})"]
      interval: 30s
      timeout: 10s
      retries: 3
```

**Step 2: Validate compose file**

```bash
docker compose config
```

Expected: No errors.

**Step 3: Start full stack**

```bash
docker compose --profile supabase up -d
docker compose ps
```

Expected: All containers up. Some may take 30–60s to become healthy (especially `auth` running migrations).

**Step 4: Verify Studio is reachable**

From the VPS:
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000
```

Expected: `200` or `301`

**Step 5: Verify Supabase API via Kong**

```bash
curl http://localhost:8000/rest/v1/ \
  -H "apikey: <YOUR_ANON_KEY>" \
  -H "Authorization: Bearer <YOUR_ANON_KEY>"
```

Expected: `{"hint":null,"details":null,"code":"PGRST000","message":"..."}`  or a JSON response (PostgREST responding).

**Step 6: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add full supabase stack with supabase profile"
```

---

## Task 6: Create Makefile

**Files:**
- Create: `Makefile`

**Step 1: Write Makefile**

```makefile
.PHONY: up up-all down restart logs ps tunnel help

# Default VPS user — override with: make tunnel VPS_USER=ubuntu VPS_HOST=1.2.3.4
VPS_USER ?= root
VPS_HOST ?= your-vps-ip-or-hostname

up: ## Start core services (postgres + redis)
	docker compose up -d

up-all: ## Start all services including Supabase stack
	docker compose --profile supabase up -d

down: ## Stop all services
	docker compose --profile supabase down

restart: down up-all ## Restart everything

logs: ## Follow logs for all running services
	docker compose logs -f

ps: ## Show service status
	docker compose --profile supabase ps

tunnel: ## Print SSH tunnel command for PC debug access
	@echo "Run this on your PC to forward all ports:"
	@echo ""
	@echo "  ssh -L 5432:localhost:5432 \\"
	@echo "      -L 6379:localhost:6379 \\"
	@echo "      -L 3000:localhost:3000 \\"
	@echo "      -L 8000:localhost:8000 \\"
	@echo "      $(VPS_USER)@$(VPS_HOST) -N"
	@echo ""
	@echo "Then connect:"
	@echo "  Postgres:  psql -h localhost -U postgres"
	@echo "  Redis:     redis-cli -h localhost"
	@echo "  Studio:    http://localhost:3000"
	@echo "  API:       http://localhost:8000"

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
```

**Step 2: Test make targets**

```bash
make help
make ps
```

**Step 3: Commit**

```bash
git add Makefile
git commit -m "chore: add Makefile with convenience targets"
```

---

## Task 7: Create README.md

**Files:**
- Create: `README.md`

**Step 1: Write README.md**

```markdown
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
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup and SSH tunnel instructions"
```

---

## End-to-End Verification Checklist

After all tasks complete, verify from your PC:

1. **SSH tunnel open** — run `ssh -L 5432:localhost:5432 -L 6379:localhost:6379 -L 3000:localhost:3000 -L 8000:localhost:8000 user@vps -N`

2. **Postgres** — `psql -h localhost -p 5432 -U postgres` — should connect and show prompt

3. **Redis** — `redis-cli -h localhost -p 6379 ping` — expected: `PONG`

4. **Studio** — open `http://localhost:3000` in browser — should show Supabase Studio UI

5. **API (Kong)** — `curl http://localhost:8000/rest/v1/ -H "apikey: <ANON_KEY>"` — should return JSON

6. **No public exposure** — from a different machine: `nc -z your-vps-ip 5432` — should timeout/refuse
