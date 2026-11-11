#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

XCADDY_VERSION="v0.4.7"
GO_IMAGE="golang:1.26.11-bookworm@sha256:79ecd0a7157c7a4cf3b281ced8465350591bf54fedab540e75374a003e1fde7e"
DEFAULTS="collections/ansible_collections/ny/vps/roles/ingress/defaults/main.yml"

if [[ ! -f "$DEFAULTS" ]]; then
  echo "Missing ingress defaults: $DEFAULTS" >&2
  exit 1
fi

read_default() {
  local key="$1"
  local value
  value="$(grep -E "^${key}:" "$DEFAULTS" | sed -E 's/^[^:]+:[[:space:]]*"([^"]+)".*/\1/')"
  if [[ -z "$value" || "$value" == "${key}:"* ]]; then
    echo "Missing or invalid ${key} in $DEFAULTS" >&2
    exit 1
  fi
  printf '%s' "$value"
}

CADDY_VERSION="$(read_default ingress_caddy_version)"
CADDY_L4_VERSION="$(read_default ingress_caddy_l4_version)"
expected="$(read_default ingress_caddy_sha256)"
ARTIFACT_BASENAME="caddy-${CADDY_VERSION}-l4-${CADDY_L4_VERSION}-linux-amd64"
ARTIFACT="dist/${ARTIFACT_BASENAME}"

mkdir -p dist
rm -f "$ARTIFACT"

docker run --rm --platform linux/amd64 \
  -v "$PWD/dist:/out:rw" \
  -e GOTOOLCHAIN=local \
  -e CGO_ENABLED=0 \
  -e GOOS=linux \
  -e GOARCH=amd64 \
  -e XCADDY_GO_BUILD_FLAGS='-trimpath -buildvcs=false' \
  -w /build \
  "$GO_IMAGE" \
  bash -ec '
    go install github.com/caddyserver/xcaddy/cmd/xcaddy@'"$XCADDY_VERSION"'
    /go/bin/xcaddy build v'"$CADDY_VERSION"' \
      --with github.com/mholt/caddy-l4@v'"$CADDY_L4_VERSION"' \
      --output /out/'"$ARTIFACT_BASENAME"'
  '

if [[ ! -f "$ARTIFACT" ]]; then
  echo "Build did not produce $ARTIFACT" >&2
  exit 1
fi

if command -v shasum >/dev/null 2>&1; then
  actual="$(shasum -a 256 "$ARTIFACT" | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
  actual="$(sha256sum "$ARTIFACT" | awk '{print $1}')"
else
  echo "Need shasum or sha256sum to verify the Caddy build." >&2
  exit 1
fi

if [[ "$actual" != "$expected" ]]; then
  echo "Caddy binary SHA-256 mismatch." >&2
  echo "  expected (ingress defaults): $expected" >&2
  echo "  actual:                      $actual" >&2
  echo "Update ingress_caddy_sha256 only after reproducible builds agree on every platform." >&2
  exit 1
fi

echo "ok: $ARTIFACT ($actual)"
