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

if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required but not installed." >&2
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
variables_json=$(gh variable list ${repo_args[@]+"${repo_args[@]}"} --json name,value 2>&1) || {
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
