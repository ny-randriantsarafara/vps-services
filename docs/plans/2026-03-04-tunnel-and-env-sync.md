# Tunnel & Env Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable `make tunnel` to execute SSH tunnel directly and add script to pull GitHub variables to local `.env`.

**Architecture:** Makefile reads VPS credentials from `.env` with shell commands; new bash script mirrors existing `sync-env-to-gh.sh` pattern for reverse sync.

**Tech Stack:** Makefile, Bash, GitHub CLI (`gh`)

---

### Task 1: Update .env.example with VPS credentials

**Files:**
- Modify: `.env.example`

**Step 1: Add VPS_USER and VPS_HOST to .env.example**

Add after the Storage section:

```
############################################
# VPS Connection (for SSH tunnel)
############################################
VPS_USER=root
VPS_HOST=your-vps-ip-or-hostname
```

**Step 2: Commit**

```bash
git add .env.example
git commit -m "Add VPS_USER and VPS_HOST to .env.example"
```

---

### Task 2: Update Makefile tunnel target

**Files:**
- Modify: `Makefile`

**Step 1: Update VPS_USER and VPS_HOST variable definitions**

Replace lines 3-5:

```makefile
# Default VPS user — override with: make tunnel VPS_USER=ubuntu VPS_HOST=1.2.3.4
VPS_USER ?= root
VPS_HOST ?= your-vps-ip-or-hostname
```

With:

```makefile
# VPS connection — reads from .env if present, override with: make tunnel VPS_USER=ubuntu VPS_HOST=1.2.3.4
VPS_USER ?= $(shell grep -s '^VPS_USER=' .env 2>/dev/null | cut -d= -f2)
VPS_HOST ?= $(shell grep -s '^VPS_HOST=' .env 2>/dev/null | cut -d= -f2)
```

**Step 2: Replace tunnel target implementation**

Replace the tunnel target (lines 24-37):

```makefile
tunnel: ## Print SSH tunnel command for PC debug access
	@echo "Run this on your PC to forward database ports:"
	@echo ""
	@echo "  ssh -L 5432:localhost:5432 \\"
	@echo "      -L 6543:localhost:6543 \\"
	@echo "      -L 6379:localhost:6379 \\"
	@echo "      $(VPS_USER)@$(VPS_HOST) -N"
	@echo ""
	@echo "Then connect:"
	@echo "  Postgres (session):      psql -h localhost -p 5432 -U postgres"
	@echo "  Postgres (transaction):  psql -h localhost -p 6543 -U postgres"
	@echo "  Redis:                   redis-cli -h localhost"
	@echo ""
	@echo "Studio and APIs are available at: https://supabase.nyhasinavalona.com"
```

With:

```makefile
tunnel: ## Open SSH tunnel for local database access (Ctrl+C to stop)
	@if [ -z "$(VPS_HOST)" ] || [ "$(VPS_HOST)" = "your-vps-ip-or-hostname" ]; then \
		echo "Error: VPS_HOST not configured. Set it in .env or run: make tunnel VPS_HOST=x.x.x.x"; \
		exit 1; \
	fi
	@echo "Opening SSH tunnel to $(VPS_USER)@$(VPS_HOST)..."
	@echo "  Postgres:  localhost:5432"
	@echo "  PgBouncer: localhost:6543"
	@echo "  Redis:     localhost:6379"
	@echo "Press Ctrl+C to stop."
	@ssh -L 5432:localhost:5432 \
	     -L 6543:localhost:6543 \
	     -L 6379:localhost:6379 \
	     $(VPS_USER)@$(VPS_HOST) -N
```

**Step 3: Test the Makefile syntax**

Run: `make help`
Expected: Shows help including `tunnel` with new description

**Step 4: Commit**

```bash
git add Makefile
git commit -m "Make tunnel target execute SSH directly instead of printing command"
```

---

### Task 3: Create sync-env-from-gh.sh script

**Files:**
- Create: `scripts/sync-env-from-gh.sh`

**Step 1: Create the script**

```bash
#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/sync-env-from-gh.sh [options]

Pull GitHub repository variables and write them to a local .env file.
This is the reverse of sync-env-to-gh.sh.

Options:
  -f, --file <path>    Output file path (default: .env)
  -r, --repo <repo>    GitHub repo in OWNER/REPO format (optional)
      --dry-run        Print actions without writing
  -h, --help           Show this help

Examples:
  scripts/sync-env-from-gh.sh
  scripts/sync-env-from-gh.sh --repo nyhasinavalona/vps-services
  scripts/sync-env-from-gh.sh --dry-run
EOF
}

env_file=".env"
repo=""
dry_run="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--file)
      env_file="$2"
      shift 2
      ;;
    -r|--repo)
      repo="$2"
      shift 2
      ;;
    --dry-run)
      dry_run="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: gh CLI is required but not installed." >&2
  echo "Install it from: https://cli.github.com/" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "Error: Not authenticated to GitHub. Run: gh auth login" >&2
  exit 1
fi

repo_args=()
if [[ -n "$repo" ]]; then
  repo_args+=(--repo "$repo")
fi

echo "Fetching repository variables..."
variables_json=$(gh variable list "${repo_args[@]}" --json name,value 2>&1) || {
  echo "Error: Failed to fetch variables. Check repo access." >&2
  echo "$variables_json" >&2
  exit 1
}

count=$(echo "$variables_json" | jq 'length')
if [[ "$count" -eq 0 ]]; then
  echo "No variables found in repository."
  exit 0
fi

if [[ "$dry_run" == "true" ]]; then
  echo "[dry-run] Would write $count variables to $env_file"
  echo "$variables_json" | jq -r '.[] | "\(.name)=***"'
  exit 0
fi

if [[ -f "$env_file" ]]; then
  backup_file="${env_file}.backup"
  cp "$env_file" "$backup_file"
  echo "Backed up existing $env_file to $backup_file"
fi

echo "$variables_json" | jq -r '.[] | "\(.name)=\(.value)"' > "$env_file"

echo "Done. Wrote $count variables to $env_file"
```

**Step 2: Make script executable**

Run: `chmod +x scripts/sync-env-from-gh.sh`

**Step 3: Test help output**

Run: `scripts/sync-env-from-gh.sh --help`
Expected: Shows usage information

**Step 4: Commit**

```bash
git add scripts/sync-env-from-gh.sh
git commit -m "Add script to pull GitHub variables to local .env"
```

---

### Task 4: Add Makefile target for sync-env-from-gh

**Files:**
- Modify: `Makefile`

**Step 1: Add sync-env target**

Add before the `help` target:

```makefile
sync-env: ## Pull GitHub repo variables to local .env
	@scripts/sync-env-from-gh.sh
```

**Step 2: Update .PHONY**

Change line 1 from:

```makefile
.PHONY: up up-all down restart logs ps tunnel help
```

To:

```makefile
.PHONY: up up-all down restart logs ps tunnel sync-env help
```

**Step 3: Test Makefile**

Run: `make help`
Expected: Shows `sync-env` target with description

**Step 4: Commit**

```bash
git add Makefile
git commit -m "Add make sync-env target for pulling GitHub variables"
```
