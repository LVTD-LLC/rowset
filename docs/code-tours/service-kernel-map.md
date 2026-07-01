# API Service Kernel Extraction Map

Use this map before extracting code from `apps/api/services.py`. The file is the
shared behavior kernel behind REST, MCP, dataset settings forms, vector tasks,
mutation history, and public preview operations. Extraction should reduce local
complexity without changing public service signatures or REST/MCP behavior.

## Kernel Boundary

Keep these boundaries stable during extraction:

- REST endpoints in `apps/api/views.py` should continue calling service
  functions and converting `DatasetServiceError` to HTTP responses.
- MCP tools in `apps/mcp_server/server.py` should continue authenticating,
  calling the same services as REST, and converting service errors to MCP tool
  errors.
- Dataset views may call service functions for settings workflows, but should
  not own dataset mutation rules.
- `apps/datasets/services.py` remains the lower-level dataset parser, export,
  filter, image preparation, and row-query helper layer.

## Caller Surfaces

| Surface | Files | What to protect |
| --- | --- | --- |
| REST API | `apps/api/views.py`, `apps/api/schemas.py` | Response shape, status codes, pagination fields, error codes |
| MCP tools | `apps/mcp_server/server.py` | Tool descriptions, structured return payloads, write-key enforcement |
| Dataset UI/settings | `apps/datasets/views.py`, `frontend/templates/datasets/*` | Form errors, public preview sessions, settings page behavior |
| Background/vector jobs | `apps/datasets/tasks.py`, `apps/datasets/vector_search.py` | Reindex/delete enqueue timing and fakeable external boundaries |
| Mutation history | `apps/datasets/history.py`, `apps/datasets/models.py` | Audit event type, metadata shape, actor attribution |

## Service Domains

| Domain | Current service functions | Main callers | Current tests |
| --- | --- | --- | --- |
| Projects and sections | `search_profile_projects`, `create_profile_project`, `update_profile_project`, `get_profile_project`, `serialize_profile_project_sections`, `create_profile_project_section`, `update_profile_project_section`, `archive_profile_project_section`, `update_profile_dataset_project` | REST project endpoints, MCP project tools, dataset settings forms | `apps/api/tests.py`, project/section tests in `apps/datasets/tests/test_csv_datasets.py` |
| Dataset lookup and serialization | `serialize_dataset_summary`, `serialize_dataset_detail`, `search_profile_datasets`, `get_profile_dataset`, `get_ready_profile_dataset` | REST dataset list/detail, MCP dataset discovery, relationship/reference helpers | `apps/api/tests.py`, `apps/mcp_server/tests/test_server.py` |
| Relationships | `create_profile_dataset_relationship`, `list_profile_dataset_relationships`, `resolve_profile_dataset_relationship`, `delete_profile_dataset_relationship` | REST relationship endpoints, MCP relationship tools, row write validation | relationship tests in `apps/datasets/tests/test_csv_datasets.py` |
| Dataset creation and typed schema inputs | `create_profile_dataset`, `_normalize_create_rows`, `_normalize_create_headers`, `_normalize_dataset_column_schema`, reference and choice validators | REST/MCP dataset creation | creation/schema tests in `apps/datasets/tests/test_csv_datasets.py`, parity tests |
| Metadata and schema mutations | `update_profile_dataset_metadata`, `update_profile_dataset_column_types`, `add_profile_dataset_column`, `rename_profile_dataset_column`, `drop_profile_dataset_column`, `reorder_profile_dataset_columns` | REST/MCP schema and metadata endpoints, dataset settings forms | schema/metadata tests in `apps/datasets/tests/test_csv_datasets.py` |
| Public previews | `update_profile_dataset_public_preview` plus public preview session behavior in dataset views | REST/MCP public preview endpoints, public dataset views | `apps/datasets/tests/test_public_previews.py`, `apps/mcp_server/tests/test_rest_mcp_parity.py` |
| Archive and restore | `archive_profile_dataset`, `restore_profile_dataset` | REST/MCP archive tools, dataset list filters, vector cleanup | archive/restore tests in `apps/datasets/tests/test_csv_datasets.py`, vector enqueue tests in `apps/api/tests.py` |
| Image assets | `attach_profile_dataset_image_asset`, `serialize_profile_dataset_asset`, `get_profile_dataset_asset`, image row/asset helpers | REST/MCP image tools, asset content endpoints | image asset tests in `apps/datasets/tests/test_csv_datasets.py` |
| Search | `search_profile_rows`, `search_profile_dataset_rows`, `list_profile_dataset_rows`, vector/lexical ranking helpers | REST/MCP search and row-list endpoints | search tests in `apps/api/tests.py`, vector tests in `apps/datasets/tests` |
| Row mutations | `create_profile_dataset_row`, `patch_profile_dataset_row`, `patch_profile_dataset_row_by_index`, `_patch_dataset_row`, `delete_profile_dataset_row`, `delete_profile_dataset_rows` | REST/MCP row create/update/delete, relationship integrity, mutation history, vector row tasks | row/mutation tests in `apps/datasets/tests/test_csv_datasets.py`, parity tests |

## Extraction Order

1. Public preview settings service.
   - Good first extraction because `apps/datasets/tests/test_public_previews.py`
     already covers read-only behavior, private metadata exclusion, password
     protection, and password-change session revocation.
   - Keep REST/MCP response shape identical with the existing parity test.

2. Mutation-history characterization.
   - Add or confirm tests for row patch, schema mutation, public preview update,
     image asset attach, and duplicate/no-op behavior before moving row or schema
     internals.
   - This should precede row mutation extraction.

3. Row mutation helpers.
   - Extract behind existing public service functions first; callers should not
     change in the same PR.
   - Preserve generated-index, unknown-column, choice/reference validation,
     relationship enforcement, vector enqueue, and mutation log semantics.

4. Schema mutation helpers.
   - Extract column add/rename/drop/reorder helpers only after row mutation and
     mutation-history expectations are stable.
   - Keep image asset cleanup and relationship column guards in the same tested
     behavior path.

5. Project and section assignment.
   - Do this after the archived-dataset project assignment product decision is
     explicit. Do not hide restore/update/archive choreography inside a refactor.

6. Search and vector orchestration.
   - Extract last. Search combines query normalization, lexical filtering, vector
     hit fusion, logging, and fakeable external boundaries. Keep this as its own
     measured change.

## Required Checks

Use the smallest relevant command first, then broaden when a public surface or
shared service contract moves:

```bash
make test -- apps/datasets/tests/test_public_previews.py -q
make test -- apps/mcp_server/tests/test_rest_mcp_parity.py -q
make test -- apps/datasets/tests/test_csv_datasets.py -k "row or schema or relationship or image" -q
make test -- apps/api apps/mcp_server -q
make coverage-high-risk -- apps/api apps/datasets apps/mcp_server -q
make lint-python
make format-check
```

## No-Go Areas

- Do not change REST or MCP public payloads while extracting internals unless the
  task is explicitly a contract change with parity tests.
- Do not move validation into REST views, MCP tools, or templates to make an
  extraction easier.
- Do not combine extraction with formatting-only churn.
- Do not add migrations for a pure service extraction.
- Do not add external network calls to tests; use fakes for vector stores,
  embeddings, storage, and provider failures.
- Do not log raw API keys, private dataset contents, uploaded asset bytes, or
  user-owned row payloads while adding observability or tests.
- Do not change archive behavior, public preview security posture, or write-key
  permission rules as an incidental side effect.

## Characterization Checklist

Before extracting a domain, write down:

- Current public service function signatures that must remain stable.
- REST endpoints and MCP tools that should behave identically after the move.
- Existing focused tests and the command that exercises them.
- Missing tests for mutation history, vector enqueue behavior, permissions, or
  error paths.
- Any production side effects such as storage cleanup, background tasks, or
  public preview session invalidation.
