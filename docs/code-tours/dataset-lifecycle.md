# Dataset Lifecycle And Agent Surfaces

This tour covers the Rowset paths agents most often change. Keep the service
layer as the source of dataset rules, then verify the public interface that
exposes the rule.

## Dataset Creation And Import

**Files to inspect**

- `apps/api/services.py` - `create_profile_dataset` and shared validation.
- `apps/datasets/services.py` - parser, header, index, and row serialization
  helpers.
- `apps/datasets/tasks.py` - async import and vector reindex handoff.
- `apps/datasets/tests/test_csv_datasets.py` - legacy import and API creation
  coverage.

**Commands**

```bash
make test -- apps/datasets/tests/test_csv_datasets.py -k "create_profile_dataset or import" -q
make lint-python
```

**Footguns**

- Do not create datasets directly in API or MCP code when a service helper should
  own validation.
- Keep headers non-empty, unique, and ordered.
- Keep index values stable and unique; use generated `rowset_id` when there is no
  reliable business key.

## Row Mutation

**Files to inspect**

- `apps/api/services.py` - row create, patch, delete, schema validation, and
  mutation history.
- `apps/datasets/history.py` - mutation record shape.
- `apps/datasets/models.py` - row uniqueness constraints.
- `apps/mcp_server/server.py` - MCP row tools.

**Commands**

```bash
make test -- apps/datasets/tests/test_csv_datasets.py -k "row or mutation" -q
make test -- apps/mcp_server/tests/test_rest_mcp_parity.py -q
```

**Footguns**

- Unknown row headers are ignored on patch, not persisted.
- Generated index columns cannot be changed by agents.
- Mutation logs must not store raw private dataset contents beyond the fields
  needed to explain the change.

## REST To Service Flow

**Files to inspect**

- `apps/api/schemas.py` - Django Ninja request and response schemas.
- `apps/api/views.py` - thin endpoint wrappers and auth selection.
- `apps/api/auth.py` - bearer API key handling and profile resolution.
- `apps/api/services.py` - shared behavior.

**Commands**

```bash
make test -- apps/api -q
make coverage-high-risk -- apps/api -q
```

**Footguns**

- Do not duplicate service validation in schemas or views.
- Use bearer auth as the preferred path; query-string keys exist for
  compatibility.
- Convert service errors to HTTP errors at the boundary.

## MCP To Service Flow

**Files to inspect**

- `apps/mcp_server/server.py` - tool descriptions, auth, service calls, and error
  conversion.
- `apps/mcp_server/auth.py` - hosted MCP bearer auth.
- `apps/mcp_server/tests/test_server.py` - tool-level contract tests.
- `apps/mcp_server/tests/test_rest_mcp_parity.py` - REST/MCP behavior parity.

**Commands**

```bash
make test -- apps/mcp_server -q
make test -- apps/mcp_server/tests/test_rest_mcp_parity.py -q
```

**Footguns**

- Keep tool descriptions concrete and user-facing.
- MCP tool bodies should authenticate, call services, convert service errors,
  and return structured data.
- Write tools must require read-write agent API keys.

## Vector Indexing And Search

**Files to inspect**

- `apps/datasets/vector_search.py` - document building, Qdrant payloads, and
  search store behavior.
- `apps/datasets/embeddings.py` - embedding provider boundary.
- `apps/datasets/tasks.py` - indexing jobs.
- `apps/api/services.py` - hybrid row search orchestration.
- `apps/datasets/tests/test_vector_search.py`,
  `apps/datasets/tests/test_vector_indexing.py`, and `apps/api/tests.py`.

**Commands**

```bash
make test -- apps/datasets/tests/test_vector_search.py apps/datasets/tests/test_vector_indexing.py apps/api/tests.py -q
make coverage-high-risk -- apps/api apps/datasets -q
```

**Footguns**

- Tests should use fake embedding providers and vector stores.
- Do not make external embedding or Qdrant calls in unit tests.
- Keep vector cleanup tied to row, dataset, archive, and schema mutation paths.

## Agent Access And API Keys

**Files to inspect**

- `apps/core/models.py` - `AgentApiKey` permissions and active state.
- `apps/core/services.py` - key creation, hashing, encryption, and lookup.
- `apps/api/auth.py` - REST auth.
- `apps/mcp_server/server.py` and `apps/mcp_server/auth.py` - MCP auth.
- `apps/core/tests/test_agent_api_keys.py`.

**Commands**

```bash
make test -- apps/core/tests/test_agent_api_keys.py apps/mcp_server/tests/test_auth.py -q
make lint-python
```

**Footguns**

- Never log raw API keys.
- Read-only keys can inspect but cannot mutate.
- Legacy profile keys should not gain new write capabilities.

## Public Previews

**Files to inspect**

- `apps/api/services.py` - public preview settings service.
- `apps/datasets/views.py` - browser preview and password flow.
- `frontend/templates/datasets/public_dataset.html` and
  `frontend/templates/datasets/public_dataset_row_detail.html`.
- `apps/datasets/tests/test_public_previews.py`.

**Commands**

```bash
make test -- apps/datasets/tests/test_public_previews.py -q
make template-check
```

**Footguns**

- Public previews are read-only browser sharing, not authentication.
- Do not expose private column descriptions or private target metadata.
- Password changes must revoke existing preview unlocks.
