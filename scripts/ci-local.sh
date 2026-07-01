#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  printf "Missing .env. Run: cp .env.example .env\n" >&2
  exit 1
fi

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$(basename "$ROOT")}"
COMPOSE_TEST=(docker compose -f docker-compose-local.yml -f docker-compose-test.yml)
CHECK_PYTHON_RUN="${COMPOSE_TEST[*]} run --rm --no-deps backend python"
PYTEST_RUN="${COMPOSE_TEST[*]} run --rm --no-deps backend pytest"

run_step() {
  printf "\n==> %s\n" "$1"
  shift
  "$@"
}

cleanup_backend_runs() {
  local containers
  containers="$(
    docker ps -aq \
      --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
      --filter "label=com.docker.compose.service=backend" \
      --filter "label=com.docker.compose.oneoff=True"
  )"

  if [[ -n "$containers" ]]; then
    # Interrupted test runs can leave one-off backend containers holding DB connections.
    docker rm -f $containers >/dev/null
  fi
}

reset_test_database() {
  "${COMPOSE_TEST[@]}" up -d db >/dev/null

  for attempt in {1..30}; do
    if "${COMPOSE_TEST[@]}" exec -T db pg_isready -U rowset -d postgres >/dev/null; then
      break
    fi
    if [[ "$attempt" -eq 30 ]]; then
      printf "Postgres did not become ready after 30 seconds.\n" >&2
      exit 1
    fi
    sleep 1
  done

  "${COMPOSE_TEST[@]}" exec -T db psql -U rowset -d postgres -v ON_ERROR_STOP=1 <<'SQL'
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'test_rowset';
DROP DATABASE IF EXISTS "test_rowset";
SQL
}

run_step "Clean stale test containers" cleanup_backend_runs
run_step "Ruff lint" make lint-python
run_step "Ruff format check" make format-check
run_step "Quality command drift check" make quality-drift-check
run_step "Production-like startup/import smoke" make startup-smoke
run_step "Scoped type check" make type-check
run_step "Install frontend dependencies" make frontend-install
run_step "Frontend lint and build" make frontend-check
run_step "Reset local test database" reset_test_database
run_step "Start backend test dependencies" "${COMPOSE_TEST[@]}" up -d db redis
run_step "Migration check" make migrations-check CHECK_PYTHON_RUN="$CHECK_PYTHON_RUN"
run_step "Django system checks" make django-check CHECK_PYTHON_RUN="$CHECK_PYTHON_RUN"
run_step "Core, docs, pages, and blog tests" make test PYTEST_RUN="$PYTEST_RUN" -- apps/core apps/docs apps/pages apps/blog -q
run_step "Dataset tests" make test PYTEST_RUN="$PYTEST_RUN" -- apps/datasets -q
run_step "API tests" make test PYTEST_RUN="$PYTEST_RUN" -- apps/api -q
run_step "MCP tests" make test PYTEST_RUN="$PYTEST_RUN" -- apps/mcp_server -q
