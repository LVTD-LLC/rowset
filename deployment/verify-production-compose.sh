#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/docker-compose-prod.yml"
sentinel="rowset-compose-secret-$$-${RANDOM}"
env_file="$(mktemp)"
rendered_config="$(mktemp)"
compose_errors="$(mktemp)"

cleanup() {
  rm -f "$env_file" "$rendered_config" "$compose_errors"
}
trap cleanup EXIT
chmod 600 "$env_file" "$rendered_config" "$compose_errors"

{
  printf 'ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:test\n'
  printf 'POSTGRES_USER=rowset\n'
  printf 'POSTGRES_PASSWORD=%s\n' "$sentinel"
  printf 'REDIS_PASSWORD=%s\n' "$sentinel"
  printf 'SECRET_KEY=%s\n' "$sentinel"
} >"$env_file"

if ! docker compose --env-file "$env_file" -f "$COMPOSE_FILE" \
  config --no-env-resolution >"$rendered_config" 2>"$compose_errors"; then
  printf 'Production Compose config validation failed.\n' >&2
  tail -n 20 "$compose_errors" >&2
  exit 1
fi

if grep -Fq "$sentinel" "$rendered_config" || grep -Fq "$sentinel" "$compose_errors"; then
  printf 'Production Compose config expanded a secret into rendered output.\n' >&2
  exit 1
fi

if ! grep -Fq '$REDIS_PASSWORD' "$rendered_config"; then
  printf 'Production Compose config lost container-side Redis password expansion.\n' >&2
  exit 1
fi

if ! docker compose --env-file "$env_file" -f "$COMPOSE_FILE" \
  config --no-env-resolution --no-interpolate --quiet 2>"$compose_errors"; then
  printf 'Secret-safe support rendering failed.\n' >&2
  tail -n 20 "$compose_errors" >&2
  exit 1
fi
