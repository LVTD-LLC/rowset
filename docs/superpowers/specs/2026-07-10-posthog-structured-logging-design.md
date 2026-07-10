# PostHog Structured Logging Design

## Goal

Send Rowset application logs to PostHog Logs through OpenTelemetry in a format that supports
high-dimensional filtering, aggregation, correlation, and incident investigation without
exporting user-owned dataset contents, credentials, request bodies, or unnecessary personal data.

## Chosen Approach

Rowset will export logs directly from each web or worker process using the OpenTelemetry Python
SDK's batched OTLP/HTTP log exporter. A dedicated logging handler will translate the existing
`structlog` event dictionaries into OpenTelemetry log bodies and flat attributes while preserving
the existing console, Sentry, and Logfire outputs.

The application will also emit one canonical completion event for each meaningful lifecycle
boundary:

- `http.request.completed` for Django, REST, and HTMX requests
- `mcp.request.completed` for FastMCP protocol and tool requests
- `background_job.completed` for Django Q worker executions

This follows PostHog's recommendation to prefer a small number of wide events over step-by-step
INFO logs. Existing domain events remain useful for payments, email delivery, dataset vector
operations, search performance, feedback delivery, and authentication failures.

## Alternatives Considered

### OpenTelemetry Collector shipping JSON stdout

This would decouple export from Django and make later routing or tail sampling easier. Rowset does
not currently operate a Collector, so this adds another deployed service, configuration surface,
and failure mode before the volume justifies it.

### Full OpenTelemetry auto-instrumentation

This would provide automatic traces and broad third-party logging. It would overlap with the
existing Sentry and Logfire setup, export noisy framework internals, and make privacy control less
explicit. It is deferred until Rowset needs distributed traces across multiple services.

## Components

### `rowset/posthog_logging.py`

Owns the PostHog OTLP bridge. It will:

- create an OpenTelemetry `LoggerProvider` with a `BatchLogRecordProcessor`
- authenticate with the existing PostHog project token via an Authorization header
- attach OpenTelemetry resource attributes to every record
- translate `structlog` event dictionaries into a string body plus flat scalar attributes
- set `event.name` to the stable event identifier used for queries
- exclude reserved logging internals and unsupported nested values
- drop centrally classified sensitive fields before export
- truncate unusually long strings to a bounded size
- preserve exception type and traceback details only when the original log explicitly requested
  exception information
- fail open so an exporter problem never interrupts an application request or worker job

The handler is attached alongside the current console handlers. It does not replace console JSON,
Sentry, or Logfire.

### `rowset/request_logging.py`

Owns request context and the canonical Django completion event. It will:

- generate a request ID, or accept a bounded safe `X-Request-ID`
- bind request context with `structlog.contextvars` so nested domain logs correlate naturally
- classify requests as `web`, `htmx`, or `rest`
- add authenticated session identity without email addresses
- accept a bounded `X-PostHog-Session-ID` from Rowset's HTMX/fetch clients for replay correlation
- emit method, normalized route name, status code/class, duration, and HTMX booleans
- return the request ID in the response header
- exclude the health-check route from canonical INFO logs
- clear context at both ends of the request so concurrent requests cannot leak fields

REST authentication will enrich the same context after API-key authentication with profile and
agent-key identifiers. The raw API key is never bound or logged.

### `rowset/mcp_logging.py`

Owns a FastMCP middleware that emits one canonical event per MCP request. It will include:

- protocol method such as `tools/call` or `tools/list`
- tool name for tool calls, but never tool arguments or results
- duration and success/failure outcome
- profile ID, agent API-key ID, and access level from verified token claims
- `posthogDistinctId` equal to the Rowset profile ID

Each MCP operation gets isolated context that is cleared after completion.

### `rowset/task_logging.py`

Uses Django Q's worker execution signals to bind job context and emit a canonical completion event.
It will include task ID, task function, task/group name, success, and duration. It will never export
task arguments, keyword arguments, or results because those may contain user dataset data or
credentials.

### Settings and deployment configuration

The integration will use explicit settings derived from environment variables:

- `POSTHOG_API_KEY`: existing `phc_` project token used by analytics and log authentication
- `POSTHOG_HOST`: defaults to `https://us.i.posthog.com`
- `POSTHOG_LOGS_ENABLED`: enables export; defaults on only for production with a configured token
- `POSTHOG_LOG_LEVEL`: defaults to `INFO`
- `POSTHOG_SERVICE_NAME`: defaults from `APP_PROCESS_TYPE` to distinguish web and worker processes

The endpoint is derived as `<POSTHOG_HOST>/i/v1/logs`. No token is included in a URL or log.
OpenTelemetry SDK and OTLP HTTP exporter packages become direct project dependencies rather than
remaining accidental transitive dependencies of Logfire.

## Resource Attribute Contract

Every PostHog log will have these OpenTelemetry resource attributes:

| Attribute | Meaning |
| --- | --- |
| `service.name` | `rowset-web` or `rowset-worker`, unless explicitly overridden |
| `service.namespace` | `rowset` |
| `service.version` | configured release or deploy commit when available |
| `deployment.environment.name` | Rowset's `ENVIRONMENT` value |
| `service.instance.id` | non-secret process instance identifier |

These fields make PostHog's service and environment facets useful and allow queries to compare
deployments and process types.

## Log Attribute Contract

Field names are stable schema, not presentation text. Shared fields include:

| Attribute | Type | Meaning |
| --- | --- | --- |
| `event.name` | string | Stable event identifier |
| `request.id` | string | Correlation identifier for one request |
| `request.interface` | string | `web`, `htmx`, `rest`, or `mcp` |
| `duration_ms` | float | End-to-end duration at the logged boundary |
| `outcome` | string | `success` or `failure` where applicable |
| `profile_id` | integer | Internal non-secret profile identifier |
| `posthogDistinctId` | string | Profile ID used by PostHog person correlation |
| `sessionId` | string | Non-secret PostHog browser session ID used for replay correlation |
| `agent_api_key_id` | integer | Database identifier, never the key value or prefix |
| `error.type` | string | Exception or stable failure category |

HTTP events add `http.request.method`, `http.route`, `http.response.status_code`,
`http.response.status_class`, `http.is_htmx`, `htmx.boosted`, and
`htmx.history_restore_request`.

MCP events add `rpc.method`, `mcp.tool.name`, and `agent_api_key_access_level`.

Background jobs add `job.id`, `job.function`, `job.name`, `job.group`, and `job.success`.

Only strings, booleans, integers, and finite floats are exported as attributes. Nested mappings,
lists, model instances, request/response objects, and serialized payloads are dropped.

## Privacy and Security Rules

The exporter will centrally drop fields whose names indicate secrets or high-risk content,
including authorization headers, API keys, tokens, passwords, secrets, cookies, request/response
bodies, payloads, properties, metadata, query values, row data, and email addresses.

Application code will also remove known unsafe existing log values rather than relying only on the
export filter. In particular:

- PostHog alias logs will no longer include cookie dictionaries, PostHog cookies, or emails.
- Email delivery logs will correlate through user/profile IDs instead of email addresses.
- Stripe webhook logs will not include Django request objects or arbitrary Stripe metadata maps.
- Vector deletion logs will record row counts instead of row ID arrays.
- Authentication logs will record outcome and credential type, never submitted credentials.

PostHog ingestion scrubbing is treated only as a possible additional safety net, not as the primary
control.

## Current Logging Coverage Audit

The current repository contains 87 application log calls, concentrated in Stripe webhook
handling, core tasks/views, dataset vector jobs, API authentication, and email delivery.

Strong existing coverage:

- Stripe lifecycle handlers include useful event, customer, subscription, profile, and status IDs.
- Hybrid search events already capture candidate counts, result counts, model details, and latency.
- Vector worker events distinguish missing targets, failure, and completion with dataset context.
- Feedback notification and email retry flows distinguish expected and actionable outcomes.

Material gaps:

- There is no shared request ID or canonical request completion log.
- REST, HTMX, and MCP operations cannot be compared consistently by duration or outcome.
- Django Q has domain-specific logs but no uniform job boundary or execution duration.
- Authentication success logs are noisy step logs and do not enrich later request logs.
- Event names mix bracket prefixes, prose, snake case, and domain-style names.
- Error logs often contain only free-form exception text rather than a queryable error type.

Unsafe or poorly queryable current values:

- full cookie maps, PostHog cookie values, and emails in alias logs
- emails in account and email-delivery logs
- a full Django request object in the Stripe webhook receipt log
- arbitrary `properties` and Stripe `metadata` mappings
- row ID lists and other non-scalar values
- inconsistent `error` values containing strings, exception objects, or tracebacks

This implementation fixes the systemic gaps and the identified high-risk call sites. It does not
rewrite every useful domain log into a new event taxonomy; future feature work should adopt the
stable field contract and wide-event pattern defined here.

## Error Handling

The OTLP exporter uses an asynchronous batch processor so request threads do not wait on PostHog.
Export failures are handled by the OpenTelemetry SDK and must not raise into Rowset business logic.
When configuration is disabled or the project token is blank, the PostHog handler is not attached
and all other logging outputs continue normally.

Canonical lifecycle emitters use `try`/`finally` so context is cleared even when downstream code
fails. They log the failure category without serializing request bodies, tool arguments, job
arguments, or exception-local variables.

## Testing Strategy

Fast unit tests will cover attribute normalization, redaction, event translation, resource
attributes, and disabled configuration without network access. Boundary tests will use a collecting
logging handler instead of mocking internal OpenTelemetry methods.

Django request middleware tests will cover normal, HTMX, REST, authenticated, server-error,
health-check, request-ID, PostHog session-ID, and context-cleanup paths. FastMCP middleware tests will
cover a successful tool call and a raised failure without logging arguments. Django Q signal tests
will cover success, failure, duration, context binding, and exclusion of task payload/result values.

Settings tests will prove that the exporter is attached only when enabled with a token and that the
web/worker service name is selected correctly. Existing focused API, MCP ASGI, worker, and core tests
will guard integration behavior. Final verification will use the Docker-backed Rowset test command,
Ruff, Django checks under production-like settings, and a clean dependency lock check.
Frontend verification will lint and build the HTMX/fetch session-correlation header wiring.

No test sends a real log to PostHog. A live smoke log requires a configured project token and should
be performed only in an explicitly authorized staging or production environment.

## Query Examples Enabled by the Schema

- Error-rate comparison by `service.name`, `deployment.environment.name`, and `service.version`
- p95 `duration_ms` grouped by `http.route` and `request.interface`
- Failed MCP tool calls filtered by `mcp.tool.name` and `agent_api_key_access_level`
- Slow Django Q jobs grouped by `job.function` and `job.group`
- All logs for a profile through `posthogDistinctId` or `profile_id`
- All nested logs for one operation through `request.id`
- HTMX-only request failures through `http.is_htmx = true` and status class

## References

- [PostHog Logs overview](https://posthog.com/docs/logs)
- [PostHog Logs start guide](https://posthog.com/docs/logs/start-here)
- [PostHog Python logs installation](https://posthog.com/docs/logs/installation/python)
- [PostHog logging best practices](https://posthog.com/docs/logs/best-practices)
- [PostHog log search](https://posthog.com/docs/logs/search)
