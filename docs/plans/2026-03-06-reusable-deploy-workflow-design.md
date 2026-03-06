# Reusable Deploy Workflow — Design Document

**Date:** 2026-03-06
**Status:** Approved
**Location:** `vps-services/.github/workflows/deploy-service.yml`

## Problem

Each service deployed to the VPS (pomodoro, future services) has its own full CI/CD workflow with duplicated SSH, Docker build, deploy, and health check logic. This doesn't scale — every new service means copy-pasting and maintaining another workflow.

## Goals

- Single reusable workflow in `vps-services/` that any service repo can call
- Covers the full pipeline: CI validation, Docker build/push, VPS deployment
- Not tied to the current architecture — works with any Dockerized service
- Minimal boilerplate per service (< 10 lines in the caller workflow)

## Non-goals

- Per-service setup hooks (database creation, etc.) — handled manually
- Caddy/routing updates — manual onboarding per service
- Infrastructure deployment (vps-services itself keeps its own workflow)

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Workflow location | `vps-services/` | Co-locates infra and deployment logic |
| Pipeline scope | CI + Build + Deploy | Full end-to-end reusable pipeline |
| CI strategy | Caller provides command via manifest | Services use different languages/tools |
| Service convention | Enforced via `deploy/manifest.yml` | Self-documenting, portable |
| .env assembly | `toJSON(secrets)` + manifest names | Dynamic secret resolution without hardcoding in workflow |
| Caddy/routing | Manual | Rare, one-time per service |
| Per-service setup | Manual | Keep workflow focused |

## Service repo convention

Every service that uses this pipeline must follow this structure:

```
<service-repo>/
├── Dockerfile                    # required — builds the production image
└── deploy/
    ├── manifest.yml              # required — drives the pipeline
    ├── compose.yml               # required — production Docker Compose
    └── .env.example              # optional — reference for required env vars
```

## Manifest schema

```yaml
# deploy/manifest.yml

# Service identity
name: <string>          # used for deploy dir and container reference
image: <string>         # full GHCR image path (without tag)

# CI validation
validate:
  command: <string>     # shell command(s) to validate the service

# Health check after deployment
health_check:
  port: <int>           # container port (default: 3000)
  path: <string>        # HTTP path (default: /)
  retries: <int>        # max attempts (default: 15)
  interval: <int>       # seconds between retries (default: 5)

# Environment variables written to .env on VPS
env:
  secrets:              # from GitHub Actions secrets
    - SECRET_NAME
  vars:                 # from GitHub Actions repository variables
    - VAR_NAME
  static:               # hardcoded key-value pairs
    KEY: "value"
```

### Example — pomodoro

```yaml
name: pomodoro
image: ghcr.io/ny-randriantsarafara/pomodoro

validate:
  command: "npm ci && npm run lint && npm run test:run"

health_check:
  port: 3000
  path: /
  retries: 15
  interval: 5

env:
  secrets:
    - DATABASE_URL
    - AUTH_SECRET
    - AUTH_GITHUB_ID
    - AUTH_GITHUB_SECRET
    - GH_CONNECTIONS_CLIENT_ID
    - GH_CONNECTIONS_CLIENT_SECRET
  vars:
    - NEXTAUTH_URL
  static:
    AUTH_TRUST_HOST: "true"
```

## Production compose convention

```yaml
# deploy/compose.yml
services:
  <service_name>:
    container_name: <service_name>
    image: <ghcr_image>:latest
    restart: unless-stopped
    env_file: .env
    networks:
      - vps-net
    healthcheck:
      test: ['CMD-SHELL', 'wget --no-verbose --tries=1 --spider http://127.0.0.1:<port> || exit 1']
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

networks:
  vps-net:
    external: true
```

## Caller workflow

Each service repo needs only this:

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  deploy:
    uses: ny-randriantsarafara/vps-services/.github/workflows/deploy-service.yml@main
    secrets: inherit
```

## Reusable workflow — pipeline overview

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   validate   │────>│   build & push   │────>│  deploy to VPS   │
│              │     │                  │     │                  │
│ - checkout   │     │ - checkout       │     │ - checkout       │
│ - install yq │     │ - read manifest  │     │ - read manifest  │
│ - read       │     │ - login GHCR     │     │ - SSH setup      │
│   manifest   │     │ - build image    │     │ - assemble .env  │
│ - run        │     │ - push to GHCR   │     │   (toJSON)       │
│   validate   │     │   (sha + latest) │     │ - sync compose   │
│   command    │     │                  │     │ - pull & start   │
│              │     │                  │     │ - health check   │
└─────────────┘     └──────────────────┘     └──────────────────┘
```

### Job 1 — Validate

- Checks out the caller repo
- Installs `yq` for YAML parsing
- Reads `validate.command` from `deploy/manifest.yml`
- Runs the command

### Job 2 — Build & Push

- Checks out the caller repo
- Reads `image` from manifest
- Logs into GHCR with `GITHUB_TOKEN`
- Builds Docker image from root `Dockerfile`
- Pushes with tags: `sha-<commit>` + `latest` (on default branch)

### Job 3 — Deploy to VPS

- Checks out the caller repo
- Reads manifest for service name, health check config
- Sets up SSH (using `VPS_SSH_KEY`, `VPS_HOST_KEY` secrets)
- Assembles `.env` by:
  1. Parsing `env.secrets`, `env.vars`, `env.static` from manifest
  2. Using `${{ toJSON(secrets) }}` and `${{ toJSON(vars) }}` to access all values
  3. Matching manifest names against JSON to build key=value pairs
- Syncs `deploy/compose.yml` to `/home/deploy/apps/<service_name>/` on VPS
- Writes assembled `.env` to the same directory
- SSHs into VPS: `docker compose pull && docker compose up -d --remove-orphans`
- Runs health check loop based on manifest config (retries, interval)
- On failure: dumps last 50 log lines and exits non-zero

### Shared secrets (in caller repo)

These must exist in every service repo that uses the workflow:

| Secret | Purpose |
|---|---|
| `VPS_SSH_KEY` | SSH private key for deploy user |
| `VPS_HOST_KEY` | VPS host key for known_hosts |
| `VPS_USER` | SSH username (e.g., `deploy`) |
| `VPS_HOST` | VPS hostname/IP |
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions |

Plus any service-specific secrets listed in the manifest's `env.secrets`.

## Onboarding a new service

1. Structure the service repo per convention (`Dockerfile`, `deploy/manifest.yml`, `deploy/compose.yml`)
2. Set GitHub secrets in the service repo (VPS + service-specific)
3. Add the 8-line caller workflow
4. Update `caddy/Caddyfile` in vps-services with the new domain route
5. Update `vps-services/docker-compose.yml` if needed (e.g., new env var for domain)
6. Perform any one-time setup (database creation, etc.) manually

## Dependencies

- `yq` (mikefarah/yq) — installed in workflow for YAML parsing
- `jq` — pre-installed on GitHub runners, used for JSON secret extraction
- Standard GitHub Actions: `actions/checkout`, `docker/login-action`, `docker/metadata-action`, `docker/build-push-action`, `webfactory/ssh-agent`
