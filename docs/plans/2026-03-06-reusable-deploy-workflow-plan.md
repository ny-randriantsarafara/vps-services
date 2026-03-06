# Reusable Deploy Workflow — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a manifest-driven reusable GitHub Actions workflow in `vps-services/` that any service repo can call to validate, build, and deploy to the VPS.

**Architecture:** A single reusable workflow (`deploy-service.yml`) reads `deploy/manifest.yml` from the caller repo using `yq`, runs CI validation, builds/pushes a Docker image to GHCR, then deploys to the VPS over SSH. Environment variables are assembled dynamically using `toJSON(secrets)` + `toJSON(vars)` matched against manifest-declared names.

**Tech Stack:** GitHub Actions (reusable workflows, `workflow_call`), `yq` (YAML parsing), `jq` (JSON secret extraction), Docker, SSH

**Repos:**
- `vps-services` at `/home/nyhasinavalona/works/vps-services`
- `pomodoro` at `/home/nyhasinavalona/works/pomodoro`

**Pinned action SHAs (from existing workflows):**
- `actions/checkout`: `11bd71901bbe5b1630ceea73d27597364c9af683` (v4.2.2)
- `docker/login-action`: `74a5d142397b4f367a81961eba4e8cd7edddf772` (v3.4.0)
- `docker/metadata-action`: `902fa8ec7d6ecbf8d84d538b9b233a880e428804` (v5.7.0)
- `docker/build-push-action`: `263435318d21b8e681c14492fe198d362a7d2c83` (v6.18.0)
- `webfactory/ssh-agent`: `a6f90b1f127823b31d4d4a8d96047790581349bd` (v0.9.0)

---

## Task 1: Create the reusable workflow in vps-services

**Files:**
- Create: `/home/nyhasinavalona/works/vps-services/.github/workflows/deploy-service.yml`

**Step 1: Create the reusable workflow file**

```yaml
# .github/workflows/deploy-service.yml
name: Deploy Service

on:
  workflow_call:

env:
  DEPLOY_BASE: /home/deploy/apps

jobs:
  validate:
    name: Validate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - name: Install yq
        run: |
          sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64
          sudo chmod +x /usr/local/bin/yq

      - name: Validate manifest exists
        run: |
          if [ ! -f deploy/manifest.yml ]; then
            echo "ERROR: deploy/manifest.yml not found"
            echo "Service repos must follow the convention: Dockerfile + deploy/manifest.yml + deploy/compose.yml"
            exit 1
          fi
          if [ ! -f deploy/compose.yml ]; then
            echo "ERROR: deploy/compose.yml not found"
            exit 1
          fi
          if [ ! -f Dockerfile ]; then
            echo "ERROR: Dockerfile not found at repo root"
            exit 1
          fi

      - name: Run service validation
        run: |
          VALIDATE_CMD=$(yq '.validate.command' deploy/manifest.yml)
          if [ "$VALIDATE_CMD" = "null" ] || [ -z "$VALIDATE_CMD" ]; then
            echo "No validate.command in manifest — skipping validation"
            exit 0
          fi
          echo "Running: $VALIDATE_CMD"
          eval "$VALIDATE_CMD"

  build:
    name: Build & Push
    runs-on: ubuntu-latest
    needs: validate
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - name: Install yq
        run: |
          sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64
          sudo chmod +x /usr/local/bin/yq

      - name: Read manifest
        id: manifest
        run: |
          echo "image=$(yq '.image' deploy/manifest.yml)" >> "$GITHUB_OUTPUT"

      - uses: docker/login-action@74a5d142397b4f367a81961eba4e8cd7edddf772 # v3.4.0
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - uses: docker/metadata-action@902fa8ec7d6ecbf8d84d538b9b233a880e428804 # v5.7.0
        id: meta
        with:
          images: ${{ steps.manifest.outputs.image }}
          tags: |
            type=sha
            type=raw,value=latest,enable={{is_default_branch}}

      - uses: docker/build-push-action@263435318d21b8e681c14492fe198d362a7d2c83 # v6.18.0
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}

  deploy:
    name: Deploy to VPS
    runs-on: ubuntu-latest
    needs: build
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - name: Install yq
        run: |
          sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64
          sudo chmod +x /usr/local/bin/yq

      - name: Read manifest
        id: manifest
        run: |
          echo "name=$(yq '.name' deploy/manifest.yml)" >> "$GITHUB_OUTPUT"
          echo "health_port=$(yq '.health_check.port // 3000' deploy/manifest.yml)" >> "$GITHUB_OUTPUT"
          echo "health_path=$(yq '.health_check.path // "/"' deploy/manifest.yml)" >> "$GITHUB_OUTPUT"
          echo "health_retries=$(yq '.health_check.retries // 15' deploy/manifest.yml)" >> "$GITHUB_OUTPUT"
          echo "health_interval=$(yq '.health_check.interval // 5' deploy/manifest.yml)" >> "$GITHUB_OUTPUT"

      - uses: webfactory/ssh-agent@a6f90b1f127823b31d4d4a8d96047790581349bd # v0.9.0
        with:
          ssh-private-key: ${{ secrets.VPS_SSH_KEY }}

      - name: Add VPS to known hosts
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.VPS_HOST_KEY }}" >> ~/.ssh/known_hosts

      - name: Assemble .env
        id: env
        env:
          ALL_SECRETS: ${{ toJSON(secrets) }}
          ALL_VARS: ${{ toJSON(vars) }}
        run: |
          ENV_FILE=$(mktemp)

          # Secrets
          KEYS=$(yq -r '.env.secrets // [] | .[]' deploy/manifest.yml)
          for key in $KEYS; do
            val=$(echo "$ALL_SECRETS" | jq -r --arg k "$key" '.[$k] // empty')
            if [ -n "$val" ]; then
              echo "${key}=${val}" >> "$ENV_FILE"
            else
              echo "WARNING: secret '$key' declared in manifest but not found in repo secrets"
            fi
          done

          # Vars
          KEYS=$(yq -r '.env.vars // [] | .[]' deploy/manifest.yml)
          for key in $KEYS; do
            val=$(echo "$ALL_VARS" | jq -r --arg k "$key" '.[$k] // empty')
            if [ -n "$val" ]; then
              echo "${key}=${val}" >> "$ENV_FILE"
            else
              echo "WARNING: var '$key' declared in manifest but not found in repo variables"
            fi
          done

          # Static
          yq -r '.env.static // {} | to_entries[] | .key + "=" + .value' deploy/manifest.yml >> "$ENV_FILE" 2>/dev/null || true

          echo "env_file=$ENV_FILE" >> "$GITHUB_OUTPUT"
          echo "Assembled $(wc -l < "$ENV_FILE") env vars"

      - name: Deploy to VPS
        env:
          VPS_USER: ${{ secrets.VPS_USER }}
          VPS_HOST: ${{ secrets.VPS_HOST }}
          SERVICE: ${{ steps.manifest.outputs.name }}
          RETRIES: ${{ steps.manifest.outputs.health_retries }}
          INTERVAL: ${{ steps.manifest.outputs.health_interval }}
          ENV_FILE: ${{ steps.env.outputs.env_file }}
        run: |
          DEPLOY_DIR="${DEPLOY_BASE}/${SERVICE}"

          # Create dir and sync files
          ssh "$VPS_USER@$VPS_HOST" "mkdir -p $DEPLOY_DIR"
          scp deploy/compose.yml "$VPS_USER@$VPS_HOST:$DEPLOY_DIR/docker-compose.yml"
          scp "$ENV_FILE" "$VPS_USER@$VPS_HOST:$DEPLOY_DIR/.env"
          rm -f "$ENV_FILE"

          # Pull, start, health check
          ssh "$VPS_USER@$VPS_HOST" bash -s <<REMOTE
            set -e
            cd "$DEPLOY_DIR"

            echo "Pulling latest image..."
            docker compose pull

            echo "Starting $SERVICE..."
            docker compose up -d --remove-orphans

            echo "Health check..."
            for i in \$(seq 1 $RETRIES); do
              CID=\$(docker compose ps -q $SERVICE 2>/dev/null)
              if [ -z "\$CID" ]; then
                echo "Attempt \$i/$RETRIES: container not found"
                sleep $INTERVAL
                continue
              fi
              STATE=\$(docker inspect --format='{{.State.Status}}' "\$CID" 2>/dev/null || echo "unknown")
              HEALTH=\$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "\$CID" 2>/dev/null || echo "unknown")
              if [ "\$STATE" = "running" ] && { [ "\$HEALTH" = "healthy" ] || [ "\$HEALTH" = "none" ]; }; then
                echo "$SERVICE is up"
                exit 0
              fi
              echo "Attempt \$i/$RETRIES: state=\$STATE health=\$HEALTH"
              sleep $INTERVAL
            done
            echo "Health check failed"
            docker compose logs $SERVICE --tail=50
            exit 1
          REMOTE
```

**Step 2: Verify YAML is valid**

Run: `cd /home/nyhasinavalona/works/vps-services && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-service.yml'))"`
Expected: No output (valid YAML)

**Step 3: Commit**

```bash
cd /home/nyhasinavalona/works/vps-services
git add .github/workflows/deploy-service.yml
git commit -m "feat: add reusable deploy-service workflow

Manifest-driven reusable workflow that any service repo can call
to validate, build Docker images, and deploy to the VPS."
```

---

## Task 2: Create pomodoro deploy manifest and compose

**Files:**
- Create: `/home/nyhasinavalona/works/pomodoro/deploy/manifest.yml`
- Rename: `/home/nyhasinavalona/works/pomodoro/deploy/docker-compose.yml` -> `/home/nyhasinavalona/works/pomodoro/deploy/compose.yml`

**Step 1: Create the manifest file**

```yaml
# deploy/manifest.yml
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

**Step 2: Rename docker-compose.yml to compose.yml**

Run: `cd /home/nyhasinavalona/works/pomodoro && git mv deploy/docker-compose.yml deploy/compose.yml`

**Step 3: Verify compose.yml content is unchanged**

Run: `cat /home/nyhasinavalona/works/pomodoro/deploy/compose.yml`
Expected: Same content as before (services.pomodoro with image, healthcheck, vps-net)

**Step 4: Commit**

```bash
cd /home/nyhasinavalona/works/pomodoro
git add deploy/manifest.yml deploy/compose.yml
git commit -m "feat: add deploy manifest and rename compose file

Adds deploy/manifest.yml for the reusable workflow convention.
Renames deploy/docker-compose.yml to deploy/compose.yml."
```

---

## Task 3: Replace pomodoro deploy workflow with caller workflow

**Files:**
- Modify: `/home/nyhasinavalona/works/pomodoro/.github/workflows/deploy.yml` (replace entirely)

**Step 1: Replace the workflow with the minimal caller**

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

**Step 2: Verify YAML is valid**

Run: `cd /home/nyhasinavalona/works/pomodoro && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))"`
Expected: No output (valid YAML)

**Step 3: Commit**

```bash
cd /home/nyhasinavalona/works/pomodoro
git add .github/workflows/deploy.yml
git commit -m "feat: migrate to reusable deploy workflow

Replaces the 162-line deploy workflow with a minimal caller
that delegates to vps-services/deploy-service.yml."
```

---

## Task 4: Update pomodoro deploy/.env.example to match manifest

**Files:**
- Modify: `/home/nyhasinavalona/works/pomodoro/deploy/.env.example`

**Step 1: Update .env.example to match the manifest env keys exactly**

Read the current file first, then update it so the variable names match what the manifest declares (particularly `GH_CONNECTIONS_CLIENT_ID` / `GH_CONNECTIONS_CLIENT_SECRET` must match what's in GitHub secrets).

Run: `cat /home/nyhasinavalona/works/pomodoro/deploy/.env.example`

Ensure the keys in `.env.example` align with the manifest. Update if needed.

**Step 2: Commit (if changes were made)**

```bash
cd /home/nyhasinavalona/works/pomodoro
git add deploy/.env.example
git commit -m "docs: align deploy env example with manifest"
```

---

## Task 5: Verify end-to-end (dry run)

**Step 1: Verify vps-services workflow YAML parses correctly**

Run: `cd /home/nyhasinavalona/works/vps-services && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-service.yml')); print('OK')"`
Expected: `OK`

**Step 2: Verify pomodoro manifest parses correctly with yq-equivalent**

Run: `cd /home/nyhasinavalona/works/pomodoro && python3 -c "import yaml; m=yaml.safe_load(open('deploy/manifest.yml')); print(f'name={m[\"name\"]}'); print(f'image={m[\"image\"]}'); print(f'secrets={m[\"env\"][\"secrets\"]}')"`
Expected: Prints `name=pomodoro`, `image=ghcr.io/ny-randriantsarafara/pomodoro`, and the secrets list

**Step 3: Verify pomodoro caller workflow references the correct path**

Run: `cd /home/nyhasinavalona/works/pomodoro && grep 'uses:' .github/workflows/deploy.yml`
Expected: `uses: ny-randriantsarafara/vps-services/.github/workflows/deploy-service.yml@main`

**Step 4: Verify compose.yml was renamed correctly**

Run: `ls /home/nyhasinavalona/works/pomodoro/deploy/`
Expected: `compose.yml  manifest.yml  .env.example` (no `docker-compose.yml`)

**Step 5: Verify no references to old docker-compose.yml remain in pomodoro**

Run: `grep -r "docker-compose.yml" /home/nyhasinavalona/works/pomodoro/.github/ /home/nyhasinavalona/works/pomodoro/deploy/ 2>/dev/null || echo "Clean"`
Expected: `Clean`
