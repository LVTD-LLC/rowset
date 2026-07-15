# SH-006: Production-safe Compose lifecycle and logging defaults

## Goal

Make the checked-in production Compose stack recover predictably after daemon or
host restarts, wait for authenticated Redis readiness, and keep Docker's local
container logs within a documented bound.

## Scope

Change `docker-compose-prod.yml`, focused production Compose tests, and the
Compose operations guidance in `SELF_HOSTING.md`. Inspect `.env.example` for
consistency, but do not add configuration knobs when fixed checked-in defaults
are sufficient. This task does not change Django, HTMX, application logging,
backups, proxy behavior, or image release policy.

## Compose design

Define one reusable YAML extension containing the operational defaults shared by
all four services:

- `restart: unless-stopped`
- Docker's `json-file` logging driver
- `max-size: 10m`
- `max-file: 3`

Merge the extension into PostgreSQL, Redis, backend, and workers. Keeping the
policy in the Compose file makes every deployment inherit it without requiring
host-wide Docker daemon changes, while the shared definition prevents service
drift.

Redis will start through a container-side shell command that reads
`REDIS_PASSWORD` at runtime. Its healthcheck will set `REDISCLI_AUTH` from the
same runtime variable and run `redis-cli ping`. Compose dollar escaping (`$$`)
will prevent host-side interpolation, keep the literal password out of the
rendered command and Docker healthcheck metadata, and avoid placing the password
in process arguments.

The Redis healthcheck will use a bounded startup grace period and retries.
Backend and workers will change their Redis dependency from `service_started` to
`service_healthy`, while retaining the healthy PostgreSQL dependency. A normal
temporary Redis startup delay will therefore hold application services at the
dependency gate instead of starting them into an avoidable crash loop.

## Documentation and support output

`SELF_HOSTING.md` will explain the restart behavior and the per-container log
bound: three 10 MB files, approximately 30 MB per service and 120 MB across the
four-service stack before Docker metadata overhead.

The troubleshooting guidance will use Compose's no-environment-resolution mode
when asking users to share rendered configuration. This preserves service
structure while avoiding expansion of `.env` values into support output. Raw
`.env`, ordinary fully resolved Compose output, and Docker container environment
metadata must still be treated as sensitive.

## Test strategy

Use the existing `rowset/tests/test_production_compose.py` integration boundary.
Tests will be written and observed failing before changing production Compose.
They will verify:

1. Every service receives the same restart and bounded logging policy.
2. Redis has an authenticated healthcheck with container-side variable
   expansion and no literal fixture secret in the rendered health command.
3. Backend and workers require healthy PostgreSQL and Redis services.
4. `docker compose config` validates the file with a temporary environment, and
   the documented support-safe rendering does not expose sentinel secrets.

After the focused Docker-backed test passes, run an isolated production Compose
Redis smoke check, inspect its health command and logging configuration, and
stop/remove only the temporary project. Run the focused test target first, then
the repository's broader local verification appropriate for this deployment-only
change.

## Rowset task lifecycle and verification limits

Move SH-006 to `Doing` when implementation starts. After local verification,
record the commands and evidence in the Rowset task notes and move it to
`Review`.

The original disposable VPS was intentionally deleted. Do not claim or mark
`Done` based on a local substitute for the task's real host-reboot and on-disk
log-rotation checks. Those two production-host checks remain explicit review
work for the next clean-room VPS deployment; once they pass, SH-006 can move to
`Done`.

## Non-goals

- No Docker daemon-wide configuration.
- No configurable logging-size environment variables.
- No application or Django logging changes.
- No HTMX, template, or browser changes.
- No host reboot, Docker Desktop restart, or mutation of unrelated containers.
- No claim that restart policies alone restart a container merely because its
  health status becomes unhealthy.
