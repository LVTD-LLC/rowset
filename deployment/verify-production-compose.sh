#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/docker-compose-prod.yml"
sentinel="rowset-compose-secret-$$-${RANDOM}"
django_secret="${sentinel}-django-$(printf 'd%.0s' {1..50})"
postgres_secret="${sentinel}-postgres-$(printf 'p%.0s' {1..32})"
redis_secret="${sentinel}-redis-$(printf 'r%.0s' {1..32})"
env_file="$(mktemp)"
rendered_config="$(mktemp)"
compose_errors="$(mktemp)"

cleanup() {
  rm -f "$env_file" "$rendered_config" "$compose_errors"
}
trap cleanup EXIT
chmod 600 "$env_file" "$rendered_config" "$compose_errors"

{
  printf 'ROWSET_IMAGE=ghcr.io/lvtd-llc/rowset:5b65d16f0a7a\n'
  printf 'ROWSET_DOMAIN=rowset.example.com\n'
  printf 'ENVIRONMENT=prod\n'
  printf 'DEBUG=off\n'
  printf 'SECRET_KEY=%s\n' "$django_secret"
  printf 'POSTGRES_DB=rowset\n'
  printf 'POSTGRES_USER=rowset\n'
  printf 'POSTGRES_HOST=db\n'
  printf 'POSTGRES_PORT=5432\n'
  printf 'POSTGRES_PASSWORD=%s\n' "$postgres_secret"
  printf 'REDIS_HOST=redis\n'
  printf 'REDIS_PORT=6379\n'
  printf 'REDIS_PASSWORD=%s\n' "$redis_secret"
} >"$env_file"

"$ROOT/deployment/self-host/validate-env.sh" "$env_file" >/dev/null

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
