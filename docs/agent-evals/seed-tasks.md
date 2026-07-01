# Rowset Agent Evaluation Seeds

Use these seeds to run repeatable Rowset coding-agent evaluations. Each seed is
small enough for one agent run and includes explicit files, fail-to-pass checks,
pass-to-pass checks, and trace notes to mine after the run.

## Runner Contract

For each seed:

1. Start from a clean branch.
2. Give the agent only the task prompt plus repo steering files.
3. Require the listed fail-to-pass check before implementation when practical.
4. Require all pass-to-pass checks before accepting the run.
5. Record changed files, commands, failures, and surprising agent behavior in the
   trace notes.

Default setup for every seed:

- Copy local env when needed with `cp .env.example .env`.
- Use Docker-backed Django tests through `make test`.
- Use fakes for embeddings, vector stores, storage errors, and external
  services.
- Do not use production API keys, OAuth tokens, or private dataset contents.
- Seed-specific setup is called out only when it differs from this default.

## Runnable Harness

List available seeds:

```bash
make agent-eval-seed
```

Create a structured dry-run artifact for a seed:

```bash
make agent-eval-seed EVAL-001
```

The command writes `result.json` and `result.md` under
`docs/agent-evals/runs/<run-id>/`. It records the seed id, prompt, expected
files, base SHA, changed-file placeholder, required checks, observed checks,
result status, and follow-up notes. This first harness does not invoke an agent
automatically; it gives humans and agents a consistent wrapper for measured
runs.

### Rowset result tracking

Generate the Rowset dataset schema payload:

```bash
uv run python scripts/agent-eval-seed.py --print-rowset-schema
```

Create that dataset through Rowset MCP with `create_dataset`, or through REST
with the printed payload. The schema is indexed by `run_id` and includes:
`seed_id`, `agent`, `model`, `base_sha`, `head_sha`, `result`, `checks_passed`,
`checks_failed`, `observed_checks`, `changed_files`, `duration_seconds`,
`cost_usd`, `failure_mode`, `notes`, and `artifact_url`.

Record or refresh a run row in an existing Rowset dataset:

```bash
uv run python scripts/agent-eval-seed.py EVAL-001 \
  --rowset-dataset-key <dataset-key> \
  --rowset-api-base https://rowset.lvtd.dev/api/ \
  --check-passed "make test -- apps/datasets apps/mcp_server -q"
```

The API key must be in `ROWSET_API_KEY` or the environment variable named by
`--rowset-api-key-env`. Do not store API keys, OAuth tokens, private dataset
contents, or full logs in eval result rows. Keep `notes` concise and use
`artifact_url` only for a private artifact location, or leave it blank.

## Seeds

### EVAL-001: Choice Column Canonicalization

- **Prompt:** Make API and MCP row writes accept unambiguous whitespace, hyphen,
  underscore, and case variants for choice values while storing the canonical
  schema choice.
- **Expected files:** `apps/api/services.py`,
  `apps/datasets/tests/test_csv_datasets.py`,
  `apps/mcp_server/tests/test_rest_mcp_parity.py`.
- **Fail-to-pass check:** Add or expose a failing test for `Ready_to-do` storing
  as `Ready to do`.
- **Pass-to-pass checks:** `make test -- apps/datasets apps/mcp_server -q`;
  `make lint-python`; `make format-check`.
- **Trace notes:** Watch whether the agent updates the shared service instead of
  patching REST and MCP separately.

### EVAL-002: Generated Index Patch Regression

- **Prompt:** Preserve existing generated-index values when agents send full-row
  patch payloads that include the unchanged generated index.
- **Expected files:** `apps/api/services.py`,
  `apps/datasets/tests/test_csv_datasets.py`.
- **Fail-to-pass check:** Add a failing test for patching a generated-index row
  with `rowset_id` unchanged.
- **Pass-to-pass checks:** `make test -- apps/datasets/tests/test_csv_datasets.py -q`;
  `make lint-python`.
- **Trace notes:** Check whether duplicate-index validation remains strict when
  the index value actually changes.

### EVAL-003: REST/MCP Dataset Creation Parity

- **Prompt:** Add a dataset-create option that is available through REST and MCP
  with identical validation and response shape.
- **Expected files:** `apps/api/schemas.py`, `apps/api/views.py`,
  `apps/api/services.py`, `apps/mcp_server/server.py`,
  `apps/mcp_server/tests/test_rest_mcp_parity.py`.
- **Fail-to-pass check:** Add a parity test that fails until both surfaces expose
  the option.
- **Pass-to-pass checks:** `make test -- apps/api apps/mcp_server -q`;
  `make coverage-high-risk -- apps/api apps/mcp_server -q`.
- **Trace notes:** Flag any duplicated validation outside the service layer.

### EVAL-004: Public Preview Password Flow

- **Prompt:** Fix a bug where changing a public-preview password must revoke
  existing unlocked preview sessions.
- **Expected files:** `apps/datasets/views.py`,
  `frontend/templates/datasets/public_dataset.html`,
  `apps/datasets/tests/test_public_previews.py`.
- **Fail-to-pass check:** Add a failing test proving the old password unlock no
  longer grants access after the password changes.
- **Pass-to-pass checks:** `make test -- apps/datasets/tests/test_public_previews.py -q`;
  `make template-check` when templates change.
- **Trace notes:** Verify public previews remain read-only and are not described
  as private authentication.

### EVAL-005: Image Asset Cleanup

- **Prompt:** Ensure failed image asset storage cleanup records retryable
  deletion rows without losing row or asset consistency.
- **Expected files:** `apps/datasets/models.py`, `apps/api/services.py`,
  `apps/datasets/tests/test_csv_datasets.py`.
- **Fail-to-pass check:** Add a failing rollback or post-delete cleanup test.
- **Pass-to-pass checks:** `make test -- apps/datasets/tests/test_csv_datasets.py -k image -q`;
  `make lint-python`.
- **Trace notes:** Check transaction boundaries and avoid printing private asset
  paths beyond synthetic test values.

### EVAL-006: Vector Search Hybrid Ranking

- **Prompt:** Adjust dataset row search ranking so exact lexical matches and
  vector hits fuse deterministically for one ready dataset.
- **Expected files:** `apps/api/services.py`,
  `apps/datasets/vector_search.py`, `apps/api/tests.py`,
  `apps/datasets/tests/test_vector_search.py`.
- **Fail-to-pass check:** Add a failing test with conflicting lexical/vector
  order and expected fused order.
- **Pass-to-pass checks:** `make test -- apps/api/tests.py apps/datasets/tests/test_vector_search.py -q`;
  `make coverage-high-risk -- apps/api apps/datasets -q`.
- **Trace notes:** Watch for accidental external embedding calls in tests.

### EVAL-007: Agent API Key Permission Boundary

- **Prompt:** Add or fix a write-path permission boundary so read-only agent API
  keys cannot mutate datasets, rows, projects, or preview settings.
- **Expected files:** `apps/api/auth.py`, `apps/mcp_server/server.py`,
  `apps/core/tests/test_agent_api_keys.py`,
  `apps/mcp_server/tests/test_server.py`.
- **Fail-to-pass check:** Add a failing write attempt with a read-only key.
- **Pass-to-pass checks:** `make test -- apps/core apps/mcp_server -q`;
  `make lint-python`.
- **Trace notes:** Ensure raw API keys never appear in logs or assertions.

### EVAL-008: Dataset Export Contract

- **Prompt:** Add a new export behavior or fix an export edge case while keeping
  CSV, JSONL, XLSX, and SQLite output stable.
- **Expected files:** `apps/datasets/services.py`, `apps/api/views.py`,
  `apps/datasets/tests/test_csv_datasets.py`.
- **Fail-to-pass check:** Add a failing export assertion for the edge case.
- **Pass-to-pass checks:** `make test -- apps/datasets/tests/test_csv_datasets.py -k export -q`;
  `make lint-python`.
- **Trace notes:** Check file content assertions, not just response status codes.

### EVAL-009: Project Section Assignment

- **Prompt:** Fix dataset project-section assignment so mismatched sections are
  rejected consistently from REST, MCP, and settings forms.
- **Expected files:** `apps/api/services.py`, `apps/api/views.py`,
  `apps/mcp_server/server.py`, `apps/datasets/views.py`,
  `apps/datasets/tests/test_csv_datasets.py`.
- **Fail-to-pass check:** Add a failing test for assigning a dataset to a section
  from another project.
- **Pass-to-pass checks:** `make test -- apps/datasets apps/api apps/mcp_server -q`.
- **Trace notes:** Watch for divergence between form errors and API errors.

### EVAL-010: Quality Gate Drift

- **Prompt:** Add a new local quality command and make CI, `make ci-local`, and
  docs agree on the exact target.
- **Expected files:** `Makefile`, `.github/workflows/ci.yml`,
  `scripts/ci-local.sh`, `docs/quality.md`.
- **Fail-to-pass check:** Show the command is absent from at least one gate before
  the change.
- **Pass-to-pass checks:** Run the new command, `make lint-python`,
  `make format-check`, and parse `.github/workflows/ci.yml`.
- **Trace notes:** Check whether the agent updates docs and local CI together,
  not only GitHub Actions.
