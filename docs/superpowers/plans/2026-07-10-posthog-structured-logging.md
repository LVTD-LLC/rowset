# PostHog Structured Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export privacy-safe Rowset logs to PostHog over batched OTLP and add canonical, queryable lifecycle events for HTTP/HTMX/REST, MCP, and Django Q work.

**Architecture:** A custom logging handler translates existing `structlog` dictionaries into flat OpenTelemetry log records and filters sensitive/non-scalar attributes before a batched OTLP exporter sees them. Django, FastMCP, and Django Q lifecycle adapters bind correlation context and emit one wide completion event at their boundaries while existing domain logs continue to console, Sentry, Logfire, and PostHog.

**Tech Stack:** Python 3.14, Django 6, structlog, OpenTelemetry Logs SDK and OTLP/HTTP exporter, FastMCP middleware, Django Q signals, pytest.

## Global Constraints

- Use `POSTHOG_API_KEY` as the `phc_` project token; never log it or put it in the endpoint URL.
- Default `POSTHOG_HOST` to `https://us.i.posthog.com` and send logs to `/i/v1/logs`.
- Preserve the existing console, Sentry, and Logfire outputs.
- Export only scalar string, boolean, integer, and finite-float attributes.
- Never export request/response bodies, query values, dataset contents, task/tool arguments or results, credentials, cookies, emails, arbitrary properties, or metadata mappings.
- Use `posthogDistinctId` containing the string form of `profile_id` for PostHog person correlation.
- Keep health-check traffic out of canonical INFO request logs.
- Use Docker-backed `make test` commands rather than host pytest for authoritative verification.

---

### Task 1: OTLP logging bridge and configuration

**Files:**
- Create: `rowset/posthog_logging.py`
- Create: `rowset/tests/test_posthog_logging.py`
- Modify: `rowset/settings.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.env.example`

**Interfaces:**
- Produces: `PostHogLoggingHandler(logging.Handler)`, `build_resource_attributes(*, service_name: str, environment: str, service_version: str, instance_id: str) -> dict[str, str]`, and `sanitize_log_attributes(event_dict: Mapping[str, Any]) -> dict[str, Scalar]`.
- Produces settings: `POSTHOG_HOST`, `POSTHOG_LOGS_ENDPOINT`, `POSTHOG_LOGS_ENABLED`, `POSTHOG_LOG_LEVEL`, and `POSTHOG_SERVICE_NAME`.
- Consumes: existing structlog records whose `record.msg` is an event dictionary after `ProcessorFormatter.wrap_for_formatter`.

- [ ] **Step 1: Write failing sanitizer and translation tests**

```python
class CollectingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_sanitize_log_attributes_keeps_queryable_scalars_and_drops_sensitive_values():
    attributes = sanitize_log_attributes(
        {
            "event": "dataset.search.completed",
            "profile_id": 42,
            "duration_ms": 12.5,
            "cached": False,
            "email": "person@example.com",
            "authorization": "Bearer secret",
            "metadata": {"private": "value"},
            "row_ids": [1, 2],
        }
    )
    assert attributes == {
        "event.name": "dataset.search.completed",
        "profile_id": 42,
        "duration_ms": 12.5,
        "cached": False,
    }


def test_posthog_handler_translates_structlog_event_for_delegate():
    delegate = CollectingHandler()
    handler = PostHogLoggingHandler(delegate=delegate)
    record = logging.LogRecord("rowset.test", logging.INFO, __file__, 1, "unused", (), None)
    record.msg = {"event": "http.request.completed", "request.id": "req-1", "profile_id": 7}
    handler.emit(record)
    exported = delegate.records[0]
    assert exported.getMessage() == "http.request.completed"
    assert getattr(exported, "event.name") == "http.request.completed"
    assert getattr(exported, "request.id") == "req-1"
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `make test rowset/tests/test_posthog_logging.py -q`

Expected: FAIL because `rowset.posthog_logging` does not exist.

- [ ] **Step 3: Add direct OpenTelemetry dependencies through uv**

Run:

```bash
uv add 'opentelemetry-sdk>=1.42.1' 'opentelemetry-exporter-otlp-proto-http>=1.42.1'
```

Expected: `pyproject.toml` and `uv.lock` declare the SDK and HTTP exporter directly.

- [ ] **Step 4: Implement the minimal bridge**

Implement `rowset/posthog_logging.py` with:

```python
Scalar = str | bool | int | float
SENSITIVE_KEY_PARTS = frozenset(
    {
        "authorization", "api_key", "token", "password", "secret", "cookie",
        "email", "request_body", "response_body", "payload", "properties",
        "metadata", "query", "row_data", "rows",
    }
)


def sanitize_log_attributes(event_dict: Mapping[str, Any]) -> dict[str, Scalar]:
    attributes: dict[str, Scalar] = {}
    event_name = event_dict.get("event")
    if isinstance(event_name, str):
        attributes["event.name"] = event_name[:1024]
    for raw_key, value in event_dict.items():
        key = str(raw_key)
        if key in {"event", "timestamp", "level", "logger", "exc_info", "stack_info"}:
            continue
        if any(part in key.lower() for part in SENSITIVE_KEY_PARTS):
            continue
        normalized = normalize_scalar(value)
        if normalized is not None:
            attributes[key] = normalized
    return attributes
```

`PostHogLoggingHandler` must accept an injected delegate for tests. Without one, construct a
`LoggerProvider(Resource.create(resource_attributes))`, an HTTP `OTLPLogExporter` using
`headers={"Authorization": f"Bearer {api_key}"}`, a `BatchLogRecordProcessor`, and an OpenTelemetry
`LoggingHandler`. Clone incoming records before changing the body or adding sanitized extras.
Remove all original custom attributes from the clone before attaching the sanitized set. Export
only `error.type` to PostHog; leave exception messages and tracebacks on the original record for
Sentry and Logfire.

- [ ] **Step 5: Configure settings and environment variables**

Add environment-backed settings near the other observability settings, then conditionally add a
`posthog` handler to the `rowset` logger only when both enabled and configured:

```python
POSTHOG_API_KEY = env("POSTHOG_API_KEY", default="")
POSTHOG_HOST = env("POSTHOG_HOST", default="https://us.i.posthog.com").rstrip("/")
POSTHOG_LOGS_ENDPOINT = f"{POSTHOG_HOST}/i/v1/logs"
POSTHOG_LOGS_ENABLED = env.bool(
    "POSTHOG_LOGS_ENABLED",
    default=ENVIRONMENT == "prod" and bool(POSTHOG_API_KEY),
)
POSTHOG_LOG_LEVEL = env("POSTHOG_LOG_LEVEL", default="INFO")
default_process_name = "worker" if env("APP_PROCESS_TYPE", default="server") == "worker" else "web"
POSTHOG_SERVICE_NAME = env("POSTHOG_SERVICE_NAME", default=f"rowset-{default_process_name}")
```

Add `.env.example` documentation for the non-secret settings and keep `POSTHOG_API_KEY` blank.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `make test rowset/tests/test_posthog_logging.py -q`

Expected: PASS with no network request.

- [ ] **Step 7: Commit the bridge**

```bash
git add rowset/posthog_logging.py rowset/tests/test_posthog_logging.py rowset/settings.py pyproject.toml uv.lock .env.example
git commit -m "feat(observability): export structured logs to PostHog"
```

### Task 2: Canonical Django, REST, and HTMX request events

**Files:**
- Create: `rowset/request_logging.py`
- Create: `rowset/tests/test_request_logging.py`
- Modify: `rowset/settings.py`
- Modify: `apps/api/auth.py`

**Interfaces:**
- Produces: `RequestLoggingMiddleware` and `bind_actor_context(*, profile_id: int, agent_api_key_id: int | None = None, agent_api_key_access_level: str = "", auth_method: str) -> None`.
- Consumes: Django `HttpRequest`, `request.htmx`, `request.resolver_match`, authenticated session user/profile, and REST authentication results.

- [ ] **Step 1: Write failing request lifecycle tests**

Cover a normal response, trusted versus invalid `X-Request-ID`, HTMX flags, REST classification,
authenticated `posthogDistinctId`, 500 outcome, health-check exclusion, and context clearing. The
core assertion shape is:

```python
def find_structlog_event(caplog, event_name: str) -> dict:
    return next(
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("event") == event_name
    )


def test_request_middleware_emits_one_wide_htmx_event(caplog):
    request = RequestFactory().get(
        "/datasets/",
        HTTP_HX_REQUEST="true",
        HTTP_HX_BOOSTED="true",
    )
    request.htmx = HtmxDetails(request)
    request.resolver_match = SimpleNamespace(view_name="dataset_list", route="datasets/")
    response = RequestLoggingMiddleware(lambda _request: HttpResponse(status=200))(request)
    event = find_structlog_event(caplog, "http.request.completed")
    assert event["request.interface"] == "htmx"
    assert event["http.route"] == "dataset_list"
    assert event["http.response.status_class"] == "2xx"
    assert event["htmx.boosted"] is True
    assert response.headers["X-Request-ID"] == event["request.id"]
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `make test rowset/tests/test_request_logging.py -q`

Expected: FAIL because the middleware module does not exist.

- [ ] **Step 3: Implement request context and wide completion log**

Use `time.perf_counter()`, `uuid4().hex`, and `structlog.contextvars`. Emit exactly one event after
the response with stable fields:

```python
logger.info(
    "http.request.completed",
    **{
        "http.request.method": request.method,
        "http.route": route_name(request),
        "http.response.status_code": status_code,
        "http.response.status_class": f"{status_code // 100}xx",
        "http.is_htmx": bool(getattr(request, "htmx", False)),
        "htmx.boosted": bool(getattr(getattr(request, "htmx", None), "boosted", False)),
        "htmx.history_restore_request": bool(
            getattr(getattr(request, "htmx", None), "history_restore_request", False)
        ),
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        "outcome": "failure" if status_code >= 500 else "success",
    },
)
```

Bind `request.id` and `request.interface` before calling the next middleware. Bind session profile
identity when available. Clear all context in a `finally` block.

- [ ] **Step 4: Enrich REST authentication context**

After resolving an API key or session profile in `apps/api/auth.py`, call:

```python
bind_actor_context(
    profile_id=profile.id,
    agent_api_key_id=getattr(agent_api_key, "id", None),
    agent_api_key_access_level=getattr(agent_api_key, "access_level", ""),
    auth_method="api_key",
)
```

Remove the per-request successful authentication INFO messages because the canonical request event
now carries that context. Keep denials at WARNING with stable `auth.outcome` and `auth.reason` fields.

- [ ] **Step 5: Register middleware after authentication**

Place `rowset.request_logging.RequestLoggingMiddleware` after Django's authentication middleware so
session actor context is available and after `django_htmx.middleware.HtmxMiddleware` so HTMX flags
are parsed.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```bash
make test rowset/tests/test_request_logging.py apps/api/tests.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit request logging**

```bash
git add rowset/request_logging.py rowset/tests/test_request_logging.py rowset/settings.py apps/api/auth.py
git commit -m "feat(observability): add canonical request logs"
```

### Task 3: Canonical FastMCP request events

**Files:**
- Create: `rowset/mcp_logging.py`
- Create: `apps/mcp_server/tests/test_logging.py`
- Modify: `apps/mcp_server/server.py`

**Interfaces:**
- Produces: `RowsetMCPLoggingMiddleware(Middleware)`.
- Consumes: FastMCP `MiddlewareContext`, `CallNext`, verified `AccessToken` claims, and `get_http_request()` only for a safe request ID header.

- [ ] **Step 1: Write failing FastMCP middleware tests**

```python
def find_structlog_event(caplog, event_name: str) -> dict:
    return next(
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("event") == event_name
    )


@pytest.mark.asyncio
async def test_mcp_logging_emits_tool_name_identity_outcome_and_duration(caplog, monkeypatch):
    middleware = RowsetMCPLoggingMiddleware()
    context = MiddlewareContext(
        message=CallToolRequestParams(name="create_dataset", arguments={"rows": ["secret"]}),
        method="tools/call",
        type="request",
        source="client",
    )
    expected_result = object()

    async def call_next(_context):
        return expected_result

    result = await middleware.on_request(context, call_next)
    event = find_structlog_event(caplog, "mcp.request.completed")
    assert event["mcp.tool.name"] == "create_dataset"
    assert event["rpc.method"] == "tools/call"
    assert event["outcome"] == "success"
    assert "arguments" not in event
    assert result is expected_result
```

Add an error-path test that asserts `error.type` but not the error message, tool arguments, or result.

- [ ] **Step 2: Run the tests and verify RED**

Run: `make test apps/mcp_server/tests/test_logging.py -q`

Expected: FAIL because `rowset.mcp_logging` does not exist.

- [ ] **Step 3: Implement and register FastMCP middleware**

Implement `on_request` with isolated structlog context, `perf_counter`, safe actor claim binding,
and a `finally` cleanup. Use `getattr(context.message, "name", "")` only for `tools/call`; never
inspect `arguments`. Register once after constructing the FastMCP instance:

```python
mcp.add_middleware(RowsetMCPLoggingMiddleware())
```

- [ ] **Step 4: Run middleware and ASGI integration tests**

Run:

```bash
make test apps/mcp_server/tests/test_logging.py apps/mcp_server/tests/test_asgi.py -q
```

Expected: PASS and existing MCP response behavior remains unchanged.

- [ ] **Step 5: Commit MCP logging**

```bash
git add rowset/mcp_logging.py apps/mcp_server/tests/test_logging.py apps/mcp_server/server.py
git commit -m "feat(observability): add canonical MCP logs"
```

### Task 4: Canonical Django Q worker events

**Files:**
- Create: `rowset/task_logging.py`
- Create: `rowset/tests/test_task_logging.py`
- Modify: `apps/core/__init__.py`

**Interfaces:**
- Produces signal receivers `bind_task_context(sender, func, task, **kwargs)` and `log_task_completion(sender, func, task, **kwargs)`.
- Consumes Django Q `pre_execute` and `post_execute_in_worker` signals.

- [ ] **Step 1: Write failing worker signal tests**

```python
def find_structlog_event(caplog, event_name: str) -> dict:
    return next(
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("event") == event_name
    )


def test_task_completion_logs_safe_job_boundary(caplog, monkeypatch):
    times = iter([10.0, 10.125])
    monkeypatch.setattr("rowset.task_logging.time.perf_counter", lambda: next(times))
    task = {
        "id": "task-1",
        "name": "Index vectors",
        "func": "apps.datasets.tasks.index_dataset_row_vector",
        "group": "vectors",
        "args": [123],
        "kwargs": {"token": "secret"},
    }
    bind_task_context(sender="django_q", func=lambda: None, task=task)
    task.update({"success": True, "result": {"private": "row data"}})
    log_task_completion(sender="django_q", func=lambda: None, task=task)
    event = find_structlog_event(caplog, "background_job.completed")
    assert event["job.id"] == "task-1"
    assert event["job.success"] is True
    assert event["duration_ms"] == 125.0
    assert "args" not in event and "result" not in event
```

Add a failure test and a test proving completion clears task context.

- [ ] **Step 2: Run the tests and verify RED**

Run: `make test rowset/tests/test_task_logging.py -q`

Expected: FAIL because `rowset.task_logging` does not exist.

- [ ] **Step 3: Implement signal-backed lifecycle logging**

Keep start times in a process-local dictionary keyed by task ID. Bind only task identity fields in
`pre_execute`; emit success, outcome, duration, and task fields in `post_execute_in_worker`; pop the
start time and clear context in all completion paths. Never read `args`, `kwargs`, or `result`.

- [ ] **Step 4: Register receivers at Django startup**

Import `rowset.task_logging` from `CoreConfig.ready()` alongside the existing signal imports so the
decorated receivers connect in both worker and test processes.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
make test rowset/tests/test_task_logging.py apps/core/tests/test_tasks.py apps/datasets/tests/test_vector_indexing.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit worker logging**

```bash
git add rowset/task_logging.py rowset/tests/test_task_logging.py apps/core/__init__.py
git commit -m "feat(observability): add canonical worker logs"
```

### Task 5: Existing log safety and queryability cleanup

**Files:**
- Modify: `apps/core/tasks.py`
- Modify: `apps/core/views.py`
- Modify: `apps/core/utils.py`
- Modify: `rowset/adapters.py`
- Modify: `apps/core/stripe_webhooks.py`
- Modify: `apps/datasets/tasks.py`
- Modify: focused existing tests under `apps/core/tests/` and `apps/datasets/tests/` when assertions change

**Interfaces:**
- Consumes: the schema and centralized filter from Task 1.
- Produces: scalar-only domain log calls with stable outcome/error fields and no known sensitive values.

- [ ] **Step 1: Add or strengthen failing assertions around unsafe log calls**

Use existing task/view/webhook tests where present. Capture the structlog event dictionaries and
assert that alias logs omit `cookies`, `posthog_cookie`, and `email`; email delivery logs omit email
addresses; Stripe logs omit request/metadata objects; and vector deletion logs use `row_count`.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
make test apps/core/tests/test_tasks.py apps/core/tests/test_views.py apps/core/tests/test_stripe_webhooks.py apps/datasets/tests/test_vector_indexing.py -q
```

Expected: at least the new privacy assertions FAIL against current log fields.

- [ ] **Step 3: Rewrite the identified high-risk log calls**

Apply these exact transformations:

- Alias logs: one final `posthog.alias.completed` event with `profile_id`, `source_function`,
  `alias_found`, and `outcome`; no cookie/email values.
- Analytics task logs: `properties_count=len(properties)` instead of the properties mapping.
- Email logs: retain `user_id`, `profile_id`, `email_type`, provider, attempt, and outcome; remove
  `email`/`email_address` fields.
- Stripe receipt: delete the full-request log because `http.request.completed` covers receipt.
- Stripe checkout logs: replace `metadata=metadata` with `metadata_count=len(metadata)` and explicit
  safe IDs already present.
- Vector deletion: replace `row_ids=row_ids` with `row_count=len(row_ids)`.
- Exception logs touched in these files: add `error_type=type(exc).__name__`; keep `exc_info=True`
  on the original record only where Sentry or Logfire benefits. The PostHog handler strips the
  message and traceback from its clone.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same focused command from Step 2.

Expected: PASS.

- [ ] **Step 5: Run a static audit for remaining high-risk log fields**

Run:

```bash
rg -n -C 3 'logger\.(info|warning|error|exception).*?(email|cookies|posthog_cookie|request=request|metadata=|properties=|row_ids=)' apps rowset -g '*.py'
```

Expected: no exported high-risk values remain; any matches are safe code context rather than log
attributes.

- [ ] **Step 6: Commit the cleanup**

```bash
git add apps/core/tasks.py apps/core/views.py apps/core/utils.py rowset/adapters.py apps/core/stripe_webhooks.py apps/datasets/tasks.py apps/core/tests apps/datasets/tests
git commit -m "refactor(observability): make domain logs privacy safe"
```

### Task 6: Integration and production-like verification

**Files:**
- Modify only files required by failures found during this verification task.

**Interfaces:**
- Consumes all earlier tasks.
- Produces fresh evidence that Rowset boots, tests, and packages the logging integration without a live PostHog call.

- [ ] **Step 1: Run the observability-focused suite**

Run:

```bash
make test rowset/tests/test_posthog_logging.py rowset/tests/test_request_logging.py rowset/tests/test_task_logging.py apps/mcp_server/tests/test_logging.py apps/mcp_server/tests/test_asgi.py apps/api/tests.py apps/core/tests/test_tasks.py apps/core/tests/test_stripe_webhooks.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Ruff on all changed Python files**

Run: `uv run ruff check rowset apps`

Expected: exit 0.

- [ ] **Step 3: Run Django's system check with export disabled**

Run: `make manage check`

Expected: exit 0 aside from already documented missing frontend build warnings.

- [ ] **Step 4: Validate production-like configuration without a network export**

Run the settings/configuration tests with `ENVIRONMENT=prod`, a fake `phc_` project token, and an
injected collecting handler. Verify the effective resource attributes select `rowset-web` for the
server and `rowset-worker` for `APP_PROCESS_TYPE=worker` without printing the token.

- [ ] **Step 5: Run the local CI-equivalent path**

Run: `make ci-local`

Expected: exit 0. If unrelated pre-existing failures occur, record their exact command/output and
still rerun every touched-area focused command after the last code change.

- [ ] **Step 6: Inspect the final diff and dependency lock**

Run:

```bash
git diff --check
uv lock --check
git status --short
```

Expected: no whitespace errors, lock is current, and only intentional task files are modified.

- [ ] **Step 7: Commit any verification fixes**

Stage only files changed by verification, then commit with:

```bash
git commit -m "fix(observability): address integration verification"
```

Skip this commit when Step 1 through Step 6 require no fixes.
