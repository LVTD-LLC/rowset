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
4. `make quality-drift-check`
5. `make startup-smoke`
6. `make type-check`
7. `make frontend-install`
8. `make frontend-check`
9. Reset the local `test_rowset` database
10. `make migrations-check`
11. `make django-check`
12. `make test -- apps/core apps/docs apps/pages apps/blog -q`
13. `make test -- apps/datasets -q`
14. `make test -- apps/api -q`
15. `make test -- apps/mcp_server -q`

Before the Docker-backed backend checks, the script removes stale Compose one-off
backend containers and resets the local `test_rowset` database. That keeps
interrupted local test runs from poisoning the next verification run.

This path intentionally mirrors the current GitHub Actions backend gate. It does
not enforce coverage or whole-repo typing until those baselines are cleaned up in
focused follow-up tasks.

## Targeted Command Matrix

| Touched area | Run this first | Add when relevant |
| --- | --- | --- |
| Models or migrations | `make migrations-check` | `make makemigrations`, then `make migrate`, only when model changes are intentional |
| Backend services, API, MCP, dataset behavior | `make test -- <pytest args>` | `make django-check` and `make migrations-check` before PR |
| Shared dataset or API behavior | `make test apps/datasets/tests/test_csv_datasets.py apps/api/tests.py apps/mcp_server/tests/test_server.py` | Add focused `-k` filters while iterating |
| Python imports, lint, or style | `make lint-python` | `make format-check`; use `make format-python` only for intentional formatting work |
| Quality command contract | `make quality-drift-check` | When editing the checker, also run `uv run python scripts/check-quality-drift.py --self-test` |
| Production startup imports | `make startup-smoke` | Docker build checks when runtime dependencies, Dockerfiles, or entrypoints change |
| Scoped low-noise typing for helpers, row contracts, schemas, service code, and app support modules | `make type-check` | Expand the typed scope only in focused type-checking work; see [typing.md](typing.md) |
| Coverage visibility | `make coverage -- <pytest args>` | Use `make coverage-high-risk -- <pytest args>` for the CI hotspot report; see [coverage.md](coverage.md) |
| Templates | `make template-check` | Run focused Django template-loading tests if rendering behavior changed |
| Frontend JavaScript or assets | `make frontend-install`, then `make frontend-check` | Run `make frontend-lint` or `make frontend-build` separately while iterating |
| Docs-only changes | Check the rendered docs path when UI rendering changed | No backend test run is required for prose-only edits |

## PR Shape For Reliability Work

Keep reliability PRs narrow enough that review can isolate the risk being
reduced. A PR may update docs with the command or behavior it changes, but avoid
bundling unrelated mechanical churn with behavior.

Good slices:

- Quality gate: `Makefile`, `.github/workflows/ci.yml`, `scripts/ci-local.sh`,
  and `docs/quality.md` for one command.
- Test split: one behavior group moved from a large test file into a focused
  test module, with no service behavior changes.
- Behavior fix: one service rule plus focused regression tests and any matching
  REST/MCP parity update.
- Docs-only tour: one code tour or task template update that names files,
  commands, and footguns.

Avoid combining:

- Broad formatting with test extraction or behavior changes.
- CI gate changes with unrelated fixture rewrites.
- Docs-only process changes with runtime service refactors.
- Migration or schema output churn with non-model reliability work.

## Warning Hygiene

Treat warnings as signal. Fix warnings when the code or test data is wrong, and
add filters only for narrow, understood framework noise.

Current allowed filters:

- `pkg_resources` deprecation noise from the test runtime.
- Django/WhiteNoise `No directory at: .../static/` during tests and startup
  smoke. Test containers and import smoke do not run `collectstatic`, while
  deployed server startup does.

When adding a warning filter, include the warning text, category, and module so
new deprecations or runtime warnings still appear in CI output.

## CI Mapping

GitHub Actions uses the same Makefile targets with host-runner command overrides
because CI already provides Postgres and Redis services:

```bash
make lint-python
make format-check
make quality-drift-check
make startup-smoke
make type-check
make frontend-install
make frontend-check
make migrations-check CHECK_PYTHON_RUN="uv run python"
make django-check CHECK_PYTHON_RUN="uv run python"
make test PYTEST_RUN="uv run pytest" -- -q
```

Local development keeps the default Docker-backed commands from `AGENTS.md`.
