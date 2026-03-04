# Design: Tunnel Execution and GitHub Env Sync

**Date:** 2026-03-04

## Overview

Two improvements to local developer workflow:

1. `make tunnel` executes the SSH tunnel directly (instead of printing the command)
2. New script to pull GitHub repository variables into local `.env`

## Task 1: Makefile Tunnel Target

### Current Behavior

The `tunnel` target prints SSH commands for the user to copy-paste.

### New Behavior

The `tunnel` target executes the SSH tunnel directly:

- Reads `VPS_USER` and `VPS_HOST` from `.env` if present
- Falls back to Makefile defaults if `.env` missing or values not set
- Command-line overrides still work: `make tunnel VPS_USER=x VPS_HOST=y`

### Implementation

```makefile
VPS_USER ?= $(shell grep -s '^VPS_USER=' .env | cut -d= -f2 || echo root)
VPS_HOST ?= $(shell grep -s '^VPS_HOST=' .env | cut -d= -f2 || echo your-vps-ip)

tunnel: ## Open SSH tunnel for local database access
	ssh -L 5432:localhost:5432 \
	    -L 6543:localhost:6543 \
	    -L 6379:localhost:6379 \
	    $(VPS_USER)@$(VPS_HOST) -N
```

### Changes Required

- Update `Makefile` tunnel target
- Add `VPS_USER` and `VPS_HOST` to `.env.example`

## Task 2: Sync Environment from GitHub

### Purpose

Pull GitHub repository variables to local `.env` file. This is the reverse of the existing `sync-env-to-gh.sh` script.

### Script: `scripts/sync-env-from-gh.sh`

**Options:**

| Flag | Description |
|------|-------------|
| `-f, --file <path>` | Output file (default: `.env`) |
| `-r, --repo <repo>` | GitHub repo in `OWNER/REPO` format |
| `--dry-run` | Print actions without writing |
| `-h, --help` | Show help |

**Behavior:**

1. Verify `gh` CLI is installed and authenticated
2. Fetch variables via `gh variable list --json name,value`
3. If target `.env` exists, backup to `.env.backup`
4. Write each variable as `KEY=VALUE`
5. Report processed count

### Error Handling

- Exit with error if `gh` CLI not installed
- Exit with error if not authenticated to GitHub
- Exit with error if repo not accessible

## Files Changed

- `Makefile` — update tunnel target
- `.env.example` — add `VPS_USER`, `VPS_HOST`
- `scripts/sync-env-from-gh.sh` — new script (create)
