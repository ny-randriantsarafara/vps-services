#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

CADDY_VERSION="2.11.7"
CADDY_L4_VERSION="0.1.2"
XCADDY_VERSION="v0.4.7"
GO_IMAGE="golang:1.26.0-bookworm@sha256:4f7e5f23bfacf4c2934ba70c132532742b6a53f01a4209e2c2eb7bd06c16f0bc"
ARTIFACT_BASENAME="caddy-${CADDY_VERSION}-l4-${CADDY_L4_VERSION}-linux-amd64"
ARTIFACT="dist/${ARTIFACT_BASENAME}"
DEFAULTS="collections/ansible_collections/ny/vps/roles/ingress/defaults/main.yml"

if [[ ! -f "$DEFAULTS" ]]; then
  echo "Missing ingress defaults: $DEFAULTS" >&2
  exit 1
fi

expected="$(grep -E '^ingress_caddy_sha256:' "$DEFAULTS" | sed -E 's/^ingress_caddy_sha256:[[:space:]]*"([^"]+)".*/\1/')"
if [[ -z "$expected" || "$expected" == ingress_caddy_sha256:* ]]; then
  echo "ingress_caddy_sha256 is missing or invalid in $DEFAULTS" >&2
  exit 1
fi

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
