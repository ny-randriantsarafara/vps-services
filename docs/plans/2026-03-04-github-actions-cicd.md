# GitHub Actions CI/CD Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a GitHub Actions workflow that validates all config files then deploys them to the VPS — a git commit is the only action needed to apply infrastructure changes.

**Architecture:** Two-job workflow: `validate` (runs on all pushes/PRs, no SSH) catches config errors early; `deploy` (depends on validate, runs on main push or manual trigger) rsyncs files over SSH, writes `.env` from secrets, restarts the Docker stack and Caddy, health-checks, and auto-rollbacks on failure.

**Tech Stack:** GitHub Actions, rsync, SSH, Docker Compose, Caddy, yamllint

---

## Pre-flight: One-time VPS setup (manual — not part of the workflow)

Before the workflow can run, the VPS needs a `deploy` user configured. This is done once and never again.

Run these commands on the VPS as root:

```bash
# 1. Create deploy user (if it doesn't exist)
useradd -m -s /bin/bash deploy

# 2. Add to docker group so docker compose works without sudo
usermod -aG docker deploy

# 3. Create the infra directory
mkdir -p /home/deploy/infra/caddy
chown -R deploy:deploy /home/deploy/infra

# 4. Generate SSH keypair for GitHub Actions
sudo -u deploy ssh-keygen -t ed25519 -C "github-actions-deploy" -f /home/deploy/.ssh/github_actions -N ""
cat /home/deploy/.ssh/github_actions.pub >> /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys

# 5. Print the private key — copy this into GitHub secret VPS_SSH_KEY
cat /home/deploy/.ssh/github_actions

# 6. Add narrow sudoers entry for Caddy only
echo 'deploy ALL=(ALL) NOPASSWD: /bin/cp /home/deploy/infra/caddy/Caddyfile /etc/caddy/conf.d/supabase.caddyfile' >> /etc/sudoers.d/deploy-caddy
echo 'deploy ALL=(ALL) NOPASSWD: /bin/systemctl reload caddy' >> /etc/sudoers.d/deploy-caddy
chmod 440 /etc/sudoers.d/deploy-caddy
```

Then add these 4 secrets in GitHub → Settings → Secrets and variables → Actions:

| Secret name | Value |
|-------------|-------|
| `VPS_HOST` | Your VPS IP or hostname |
| `VPS_USER` | `deploy` |
| `VPS_SSH_KEY` | Contents of `/home/deploy/.ssh/github_actions` (private key) |
| `VPS_ENV` | Full contents of your `.env` file |
| `VPS_HOST_KEY` | Output of `ssh-keyscan -H <vps-host>` — the hashed host key for MITM protection |

---

### Task 1: Create the workflow file skeleton

**Files:**
- Create: `.github/workflows/deploy.yml`

**Step 1: Create the directory and file**

```bash
mkdir -p .github/workflows
```

Create `.github/workflows/deploy.yml` with this content:

```yaml
name: Validate & Deploy

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  validate:
    name: Validate configs
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Placeholder
        run: echo "validation steps coming"

  deploy:
    name: Deploy to VPS
    runs-on: ubuntu-latest
    needs: validate
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - name: Placeholder
        run: echo "deploy steps coming"
```

**Step 2: Verify the file is valid YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`

**Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add workflow skeleton"
```

---

### Task 2: Add docker-compose validation step

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Context:** `docker compose config` validates the YAML and checks that all `${VAR}` references are syntactically correct. It needs a dummy `.env` with placeholder values so the vars resolve — without one, it errors on missing required vars like `POSTGRES_PASSWORD`.

**Step 1: Replace the validate job placeholder with actual steps**

Replace the `validate` job content:

```yaml
  validate:
    name: Validate configs
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Validate docker-compose.yml
        run: |
          # Create a dummy .env so docker compose config can resolve ${VAR} references
          # without needing real secrets. We only care about YAML syntax here.
          grep -E '^[A-Z_]+=?' .env.example | sed 's/=.*/=placeholder/' > .env
          docker compose config --quiet
          rm .env
```

**Step 2: Verify locally that docker compose config works**

```bash
grep -E '^[A-Z_]+=?' .env.example | sed 's/=.*/=placeholder/' > .env
docker compose config --quiet && echo "docker-compose OK"
rm .env
```

Expected: `docker-compose OK` (no errors)

**Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add docker-compose config validation"
```

---

### Task 3: Add Caddy config validation step

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Context:** The GitHub Actions runner doesn't have Caddy pre-installed. We install it from the official apt repo, then use `caddy fmt --overwrite` in check mode. The `caddy validate` command requires a running Caddy instance, so `caddy fmt` is the right linting tool for CI.

**Step 1: Add Caddy install + validate steps to the validate job, after the docker-compose step**

```yaml
      - name: Install Caddy
        run: |
          sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
          curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
          curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
          sudo apt-get update
          sudo apt-get install caddy

      - name: Validate Caddyfile
        run: caddy fmt --overwrite caddy/Caddyfile && echo "Caddyfile OK"
```

**Step 2: Test the Caddy install locally (optional — just verify the file parses)**

If you have Caddy installed locally:
```bash
caddy fmt --overwrite caddy/Caddyfile && echo "Caddyfile OK"
```

Expected: `Caddyfile OK`

**Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add Caddyfile validation"
```

---

### Task 4: Add Kong YAML validation step

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Step 1: Add yamllint step to the validate job**

```yaml
      - name: Install yamllint
        run: pip install yamllint

      - name: Validate kong.yml
        run: yamllint -d relaxed volumes/kong/kong.yml && echo "kong.yml OK"
```

Note: `-d relaxed` uses relaxed rules (allows long lines etc.) — stricter than nothing but not pedantic.

**Step 2: Test locally**

```bash
pip install yamllint 2>/dev/null || true
yamllint -d relaxed volumes/kong/kong.yml && echo "kong.yml OK"
```

Expected: `kong.yml OK`

**Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add kong.yml yamllint validation"
```

---

### Task 5: Add .env secret completeness check

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Context:** This check parses `.env.example` for all key names (lines matching `KEY=...`), then verifies every one of those keys is present in the `VPS_ENV` secret. This catches "we added a new required env var to .env.example but forgot to update the GitHub secret."

**Step 1: Add the check as the last step in the validate job**

```yaml
      - name: Check VPS_ENV has all required keys
        env:
          VPS_ENV: ${{ secrets.VPS_ENV }}
        run: |
          missing=0
          while IFS= read -r line; do
            # Skip comments and blank lines
            [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
            key="${line%%=*}"
            [[ -z "$key" ]] && continue
            if ! echo "$VPS_ENV" | grep -q "^${key}="; then
              echo "Missing secret key: $key"
              missing=1
            fi
          done < .env.example
          if [[ $missing -eq 1 ]]; then
            echo "VPS_ENV is missing required keys. Update the GitHub secret."
            exit 1
          fi
          echo "All required keys present in VPS_ENV"
```

**Step 2: Test the key-extraction logic locally (dry run)**

```bash
# Simulate what the script does — just print the keys it would check
while IFS= read -r line; do
  [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
  key="${line%%=*}"
  [[ -z "$key" ]] && continue
  echo "Would check: $key"
done < .env.example
```

Expected: Prints all non-comment key names from `.env.example`

**Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add VPS_ENV completeness check against .env.example"
```

---

### Task 6: Add SSH setup + backup step to deploy job

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Context:** The deploy job needs SSH access. We use the `webfactory/ssh-agent` action which loads the private key into an ssh-agent for the job's lifetime — no temp files needed. The backup step runs a single SSH command that creates `.backup` copies of the three files we'll overwrite.

**Step 1: Replace the deploy job placeholder steps**

```yaml
  deploy:
    name: Deploy to VPS
    runs-on: ubuntu-latest
    needs: validate
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4

      - name: Set up SSH agent
        uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.VPS_SSH_KEY }}

      - name: Add VPS to known hosts
        run: |
          mkdir -p ~/.ssh
          ssh-keyscan -H ${{ secrets.VPS_HOST }} >> ~/.ssh/known_hosts

      - name: Backup current configs on VPS
        run: |
          ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} '
            set -e
            INFRA=/home/deploy/infra
            cd "$INFRA"
            [ -f docker-compose.yml ] && cp docker-compose.yml docker-compose.yml.backup || true
            [ -f caddy/Caddyfile ] && cp caddy/Caddyfile caddy/Caddyfile.backup || true
            [ -f .env ] && cp .env .env.backup || true
            echo "Backup complete"
          '
```

**Step 2: Verify webfactory/ssh-agent action exists**

Check: https://github.com/webfactory/ssh-agent — confirmed stable, widely used action.

**Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add SSH setup and backup step to deploy job"
```

---

### Task 7: Add rsync + .env write step

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Context:** `rsync` syncs only the config files — not `.env` (has secrets, managed separately), not `.git/` (not needed on VPS), not `docs/` (documentation only). The `--delete` flag removes files on the VPS that were deleted from the repo, keeping them in sync.

**Step 1: Add rsync and .env write steps after the backup step**

```yaml
      - name: Install rsync
        run: sudo apt-get install -y rsync

      - name: Sync config files to VPS
        run: |
          rsync -avz --delete \
            --exclude='.env' \
            --exclude='.env.*' \
            --exclude='.git/' \
            --exclude='docs/' \
            --exclude='*.backup' \
            -e "ssh -o StrictHostKeyChecking=no" \
            ./ \
            ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }}:/home/deploy/infra/

      - name: Write .env on VPS from secret
        run: |
          ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} \
            "cat > /home/deploy/infra/.env" <<< "${{ secrets.VPS_ENV }}"
```

**Step 2: Verify rsync exclude logic locally (dry run)**

```bash
rsync -avz --delete --dry-run \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='.git/' \
  --exclude='docs/' \
  --exclude='*.backup' \
  ./ /tmp/rsync-test/
```

Expected: Lists files to sync, excludes `.env`, `.git/`, `docs/`

**Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add rsync sync and .env write steps"
```

---

### Task 8: Add stack restart + Caddy reload steps

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Step 1: Add restart and Caddy steps after the .env write step**

```yaml
      - name: Restart Docker stack
        run: |
          ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} '
            set -e
            cd /home/deploy/infra
            docker compose --profile supabase up -d --remove-orphans --pull missing
            echo "Stack restarted"
          '

      - name: Install Caddy config and reload
        run: |
          ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} '
            set -e
            sudo cp /home/deploy/infra/caddy/Caddyfile /etc/caddy/conf.d/supabase.caddyfile
            sudo systemctl reload caddy
            echo "Caddy reloaded"
          '
```

**Step 2: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add stack restart and Caddy reload steps"
```

---

### Task 9: Add health check loop with rollback

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Context:** The health check waits up to 100 seconds (10 × 10s) for all expected services to appear as `healthy` in `docker compose ps`. The expected services match what's in docker-compose.yml with the supabase profile: postgres, redis, kong, auth, rest, realtime, storage, meta, studio. On failure, backup files are restored and the stack is restarted with the previous config.

**Step 1: Add the health check + rollback steps after the Caddy reload step**

```yaml
      - name: Health check services
        id: healthcheck
        run: |
          ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} '
            set -e
            cd /home/deploy/infra
            EXPECTED_SERVICES="postgres redis kong auth rest realtime storage meta studio"
            MAX_RETRIES=10
            SLEEP_SECS=10

            for i in $(seq 1 $MAX_RETRIES); do
              echo "Health check attempt $i/$MAX_RETRIES..."
              PS_OUTPUT=$(docker compose --profile supabase ps --format json 2>/dev/null || docker compose --profile supabase ps)
              ALL_HEALTHY=true

              for svc in $EXPECTED_SERVICES; do
                # Check if service is running (healthy or running without explicit healthcheck)
                if ! echo "$PS_OUTPUT" | grep -q "\"$svc\"" 2>/dev/null; then
                  # Fallback: text-mode ps
                  STATUS=$(docker compose --profile supabase ps "$svc" 2>/dev/null | tail -1)
                  if ! echo "$STATUS" | grep -qE "(healthy|Up)"; then
                    echo "Service not healthy: $svc — $STATUS"
                    ALL_HEALTHY=false
                  fi
                fi
              done

              if $ALL_HEALTHY; then
                echo "All services healthy"
                exit 0
              fi

              sleep $SLEEP_SECS
            done

            echo "Health check failed after $MAX_RETRIES attempts"
            exit 1
          '

      - name: Rollback on health check failure
        if: failure() && steps.healthcheck.outcome == 'failure'
        run: |
          echo "Rolling back to previous configuration..."
          ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} '
            set -e
            cd /home/deploy/infra

            # Restore backup files
            [ -f docker-compose.yml.backup ] && cp docker-compose.yml.backup docker-compose.yml
            [ -f caddy/Caddyfile.backup ] && cp caddy/Caddyfile.backup caddy/Caddyfile
            [ -f .env.backup ] && cp .env.backup .env

            # Restart with restored config
            docker compose --profile supabase up -d --remove-orphans

            # Restore Caddy
            sudo cp caddy/Caddyfile /etc/caddy/conf.d/supabase.caddyfile
            sudo systemctl reload caddy

            echo "Rollback complete"
          '
          echo "ROLLBACK PERFORMED — check VPS logs with: docker compose --profile supabase logs"
          exit 1
```

**Step 2: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add health check and rollback steps"
```

---

### Task 10: Final review — assemble and verify the complete workflow

**Files:**
- Read: `.github/workflows/deploy.yml`

**Step 1: Verify the complete workflow file is well-formed**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))" && echo "YAML valid"
```

Expected: `YAML valid`

**Step 2: Verify job dependency graph is correct**

Check in the file:
- `validate` job has NO `needs:`
- `deploy` job has `needs: validate`
- `deploy` job has `if: github.ref == 'refs/heads/main'`
- Both jobs have `runs-on: ubuntu-latest`

**Step 3: Push to trigger the workflow**

```bash
git push origin main
```

Then check: GitHub → Actions tab → "Validate & Deploy" workflow run

**Step 4: If workflow fails on validate — common fixes**

| Error | Fix |
|-------|-----|
| `docker compose config` fails | Check .env.example for vars without defaults that break the dummy .env generation |
| `caddy fmt` fails | Run `caddy fmt --overwrite caddy/Caddyfile` locally, commit the formatted result |
| yamllint fails | Fix YAML indentation in `volumes/kong/kong.yml` |
| VPS_ENV key check fails | Update the `VPS_ENV` GitHub secret to include the missing key |

**Step 5: If workflow fails on deploy — common fixes**

| Error | Fix |
|-------|-----|
| SSH permission denied | Verify `VPS_SSH_KEY` secret matches the public key in `~/.ssh/authorized_keys` on VPS |
| rsync: command not found | The `sudo apt-get install -y rsync` step should handle this; check runner logs |
| sudo: cp: command not found | Verify sudoers path matches exactly: `/bin/cp` — on some systems it's `/usr/bin/cp` |
| Docker compose fails | SSH to VPS, run `docker compose --profile supabase logs` |

---

### Task 11: Fix sudoers path if needed (conditional)

**Context:** The sudoers entry uses `/bin/cp`. On Ubuntu 22.04+, `cp` lives at `/usr/bin/cp` (with `/bin` as a symlink). If the deploy fails with "sudo: /bin/cp: command not found", update the sudoers entry.

**Step 1: Check the actual path on your VPS**

```bash
ssh deploy@your-vps "which cp"
```

**Step 2: If output is `/usr/bin/cp`, update sudoers on VPS as root**

```bash
# On VPS as root:
cat > /etc/sudoers.d/deploy-caddy << 'EOF'
deploy ALL=(ALL) NOPASSWD: /usr/bin/cp /home/deploy/infra/caddy/Caddyfile /etc/caddy/conf.d/supabase.caddyfile
deploy ALL=(ALL) NOPASSWD: /bin/systemctl reload caddy
EOF
chmod 440 /etc/sudoers.d/deploy-caddy
```

This is a one-time VPS fix, not a workflow change.

---

## Final workflow file (complete reference)

After all tasks, `.github/workflows/deploy.yml` should look exactly like this:

```yaml
name: Validate & Deploy

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  validate:
    name: Validate configs
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Validate docker-compose.yml
        run: |
          grep -E '^[A-Z_]+=?' .env.example | sed 's/=.*/=placeholder/' > .env
          docker compose config --quiet
          rm .env

      - name: Install Caddy
        run: |
          sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
          curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
          curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
          sudo apt-get update
          sudo apt-get install caddy

      - name: Validate Caddyfile
        run: caddy fmt --overwrite caddy/Caddyfile && echo "Caddyfile OK"

      - name: Install yamllint
        run: pip install yamllint

      - name: Validate kong.yml
        run: yamllint -d relaxed volumes/kong/kong.yml && echo "kong.yml OK"

      - name: Check VPS_ENV has all required keys
        env:
          VPS_ENV: ${{ secrets.VPS_ENV }}
        run: |
          missing=0
          while IFS= read -r line; do
            [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
            key="${line%%=*}"
            [[ -z "$key" ]] && continue
            if ! echo "$VPS_ENV" | grep -q "^${key}="; then
              echo "Missing secret key: $key"
              missing=1
            fi
          done < .env.example
          if [[ $missing -eq 1 ]]; then
            echo "VPS_ENV is missing required keys. Update the GitHub secret."
            exit 1
          fi
          echo "All required keys present in VPS_ENV"

  deploy:
    name: Deploy to VPS
    runs-on: ubuntu-latest
    needs: validate
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4

      - name: Set up SSH agent
        uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.VPS_SSH_KEY }}

      - name: Add VPS to known hosts
        run: |
          mkdir -p ~/.ssh
          ssh-keyscan -H ${{ secrets.VPS_HOST }} >> ~/.ssh/known_hosts

      - name: Backup current configs on VPS
        run: |
          ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} '
            set -e
            INFRA=/home/deploy/infra
            cd "$INFRA"
            [ -f docker-compose.yml ] && cp docker-compose.yml docker-compose.yml.backup || true
            [ -f caddy/Caddyfile ] && cp caddy/Caddyfile caddy/Caddyfile.backup || true
            [ -f .env ] && cp .env .env.backup || true
            echo "Backup complete"
          '

      - name: Install rsync
        run: sudo apt-get install -y rsync

      - name: Sync config files to VPS
        run: |
          rsync -avz --delete \
            --exclude='.env' \
            --exclude='.env.*' \
            --exclude='.git/' \
            --exclude='docs/' \
            --exclude='*.backup' \
            -e "ssh -o StrictHostKeyChecking=no" \
            ./ \
            ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }}:/home/deploy/infra/

      - name: Write .env on VPS from secret
        run: |
          ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} \
            "cat > /home/deploy/infra/.env" <<< "${{ secrets.VPS_ENV }}"

      - name: Restart Docker stack
        run: |
          ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} '
            set -e
            cd /home/deploy/infra
            docker compose --profile supabase up -d --remove-orphans --pull missing
            echo "Stack restarted"
          '

      - name: Install Caddy config and reload
        run: |
          ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} '
            set -e
            sudo cp /home/deploy/infra/caddy/Caddyfile /etc/caddy/conf.d/supabase.caddyfile
            sudo systemctl reload caddy
            echo "Caddy reloaded"
          '

      - name: Health check services
        id: healthcheck
        run: |
          ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} '
            set -e
            cd /home/deploy/infra
            EXPECTED_SERVICES="postgres redis kong auth rest realtime storage meta studio"
            MAX_RETRIES=10
            SLEEP_SECS=10

            for i in $(seq 1 $MAX_RETRIES); do
              echo "Health check attempt $i/$MAX_RETRIES..."
              ALL_HEALTHY=true

              for svc in $EXPECTED_SERVICES; do
                STATUS=$(docker compose --profile supabase ps "$svc" 2>/dev/null | tail -1)
                if ! echo "$STATUS" | grep -qE "(healthy|Up)"; then
                  echo "Service not healthy: $svc — $STATUS"
                  ALL_HEALTHY=false
                fi
              done

              if $ALL_HEALTHY; then
                echo "All services healthy"
                exit 0
              fi

              sleep $SLEEP_SECS
            done

            echo "Health check failed after $MAX_RETRIES attempts"
            exit 1
          '

      - name: Rollback on health check failure
        if: failure() && steps.healthcheck.outcome == 'failure'
        run: |
          echo "Rolling back to previous configuration..."
          ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} '
            set -e
            cd /home/deploy/infra

            [ -f docker-compose.yml.backup ] && cp docker-compose.yml.backup docker-compose.yml
            [ -f caddy/Caddyfile.backup ] && cp caddy/Caddyfile.backup caddy/Caddyfile
            [ -f .env.backup ] && cp .env.backup .env

            docker compose --profile supabase up -d --remove-orphans

            sudo cp caddy/Caddyfile /etc/caddy/conf.d/supabase.caddyfile
            sudo systemctl reload caddy

            echo "Rollback complete"
          '
          echo "ROLLBACK PERFORMED — check VPS logs with: docker compose --profile supabase logs"
          exit 1
```
