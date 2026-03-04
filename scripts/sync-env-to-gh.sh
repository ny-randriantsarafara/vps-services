#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/sync-env-to-gh.sh [options]

Read KEY=VALUE entries from a .env file and push each key to GitHub Actions
repository settings using the gh CLI.

Options:
  -f, --file <path>    .env file path (default: .env)
  -r, --repo <repo>    GitHub repo in OWNER/REPO format (optional)
      --secret         Write as GitHub Actions secrets (gh secret set)
      --var            Write as GitHub Actions variables (gh variable set, default)
      --dry-run        Print actions without calling gh
      --allow-empty    Include keys with empty values
  -h, --help           Show this help

Examples:
  scripts/sync-env-to-gh.sh
  scripts/sync-env-to-gh.sh --repo nyhasinavalona/vps-services --secret
EOF
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

env_file=".env"
repo=""
target="var"
dry_run="false"
allow_empty="false"

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
    --secret)
      target="secret"
      shift
      ;;
    --var)
      target="var"
      shift
      ;;
    --dry-run)
      dry_run="true"
      shift
      ;;
    --allow-empty)
      allow_empty="true"
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
  echo "gh CLI is required but not installed." >&2
  exit 1
fi

if [[ ! -f "$env_file" ]]; then
  echo "File not found: $env_file" >&2
  exit 1
fi

repo_args=()
if [[ -n "$repo" ]]; then
  repo_args+=(--repo "$repo")
fi

set_var() {
  local key="$1"
  local value="$2"

  if [[ "$dry_run" == "true" ]]; then
    if [[ "$target" == "secret" ]]; then
      echo "[dry-run] gh secret set $key ${repo:+--repo $repo} --body ***"
    else
      echo "[dry-run] gh variable set $key ${repo:+--repo $repo} --body ***"
    fi
    return
  fi

  if [[ "$target" == "secret" ]]; then
    gh secret set "$key" "${repo_args[@]}" --body "$value"
  else
    gh variable set "$key" "${repo_args[@]}" --body "$value"
  fi
}

processed=0
skipped=0

while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
  line="${raw_line%$'\r'}"
  trimmed="$(trim "$line")"

  [[ -z "$trimmed" ]] && continue
  [[ "$trimmed" == \#* ]] && continue

  if [[ "$trimmed" =~ ^export[[:space:]]+ ]]; then
    trimmed="${trimmed#export}"
    trimmed="$(trim "$trimmed")"
  fi

  if [[ "$trimmed" != *=* ]]; then
    echo "Skipping invalid line (missing '='): $line" >&2
    skipped=$((skipped + 1))
    continue
  fi

  key_part="${trimmed%%=*}"
  value_part="${trimmed#*=}"
  key="$(trim "$key_part")"
  value="$value_part"

  if [[ -z "$key" ]]; then
    echo "Skipping invalid line (empty key): $line" >&2
    skipped=$((skipped + 1))
    continue
  fi

  if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "Skipping invalid key '$key'" >&2
    skipped=$((skipped + 1))
    continue
  fi

  if [[ -z "$value" && "$allow_empty" != "true" ]]; then
    echo "Skipping empty value for key: $key (use --allow-empty to include)"
    skipped=$((skipped + 1))
    continue
  fi

  set_var "$key" "$value"
  processed=$((processed + 1))
done < "$env_file"

echo "Done. Processed: $processed, Skipped: $skipped"
