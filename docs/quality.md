# Rowset Quality Commands

This is the command contract for local verification and CI-equivalent checks.
Use it before adding new gates so agents and humans run the same commands.

## Full Local CI Path

Run this before opening a PR when you need the current required CI equivalent:

```bash
cp .env.example .env  # first local run only
make ci-local
```

`make ci-local` runs, in order:

1. Remove stale Docker Compose one-off backend containers
2. `make lint-python`
3. `make format-check`
4. `make frontend-install`
5. `make frontend-check`
6. Reset the local `test_rowset` database
7. `make migrations-check`
8. `make django-check`
9. `make test -- apps/core apps/docs apps/pages apps/blog -q`
10. `make test -- apps/datasets -q`
11. `make test -- apps/api -q`
12. `make test -- apps/mcp_server -q`

Before the Docker-backed backend checks, the script removes stale Compose one-off
backend containers and resets the local `test_rowset` database. That keeps
interrupted local test runs from poisoning the next verification run.

This path intentionally mirrors the current GitHub Actions backend gate. It does
not enforce coverage or typing until their baselines are cleaned up in focused
follow-up tasks.

## Targeted Command Matrix

| Touched area | Run this first | Add when relevant |
| --- | --- | --- |
| Models or migrations | `make migrations-check` | `make makemigrations`, then `make migrate`, only when model changes are intentional |
| Backend services, API, MCP, dataset behavior | `make test -- <pytest args>` | `make django-check` and `make migrations-check` before PR |
| Shared dataset or API behavior | `make test apps/datasets/tests/test_csv_datasets.py apps/api/tests.py apps/mcp_server/tests/test_server.py` | Add focused `-k` filters while iterating |
| Python imports, lint, or style | `make lint-python` | `make format-check`; use `make format-python` only for intentional formatting work |
| Scoped low-noise typing | `make type-check` | Expand the typed scope only in focused type-checking work |
| Coverage visibility | `make coverage -- <pytest args>` | Use `make coverage-high-risk -- <pytest args>` for the CI hotspot report; see [coverage.md](coverage.md) |
| Templates | `make template-check` | Run focused Django template-loading tests if rendering behavior changed |
| Frontend JavaScript or assets | `make frontend-install`, then `make frontend-check` | Run `make frontend-lint` or `make frontend-build` separately while iterating |
| Docs-only changes | Check the rendered docs path when UI rendering changed | No backend test run is required for prose-only edits |

## CI Mapping

GitHub Actions uses the same Makefile targets with host-runner command overrides
because CI already provides Postgres and Redis services:

```bash
make lint-python
make format-check
make frontend-install
make frontend-check
make migrations-check CHECK_PYTHON_RUN="uv run python"
make django-check CHECK_PYTHON_RUN="uv run python"
make test PYTEST_RUN="uv run pytest" -- -q
```

Local development keeps the default Docker-backed commands from `AGENTS.md`.
