# Rowset Hybrid Search V1 Scope

## Decision

V1 is authenticated dataset-level hybrid row search for agents and REST callers.
It indexes ready Rowset dataset rows, combines vector and lexical matches, and
returns hydrated canonical Rowset rows with match metadata.

This is intentionally not a public-preview search feature, cross-dataset
knowledge base, dashboard search UI, or external-source sync system.

## Primary Users

- Agents using hosted Rowset MCP to retrieve context from a known dataset.
- Developers using Rowset REST with bearer API keys.
- Operators backfilling or debugging the retrieval index.

## Supported Surfaces

### MCP

Agents call `search_dataset_rows` with:

```json
{
  "dataset_key": "9f2f33dc-aa19-43a6-a9c6-087f2ba08c15",
  "query": "how do we avoid stale vectors?",
  "filters": {"status": "review"},
  "limit": 5
}
```

### REST

Authenticated callers use:

```http
POST /api/datasets/{dataset_key}/search
Authorization: Bearer <ROWSET_API_KEY>
Content-Type: application/json

{
  "query": "ROW-VEC-001",
  "filters": {"area": "Product"},
  "limit": 10
}
```

## Result Shape

Each result returns a hydrated Rowset row plus ranking and source metadata:

```json
{
  "rank": 1,
  "score": 0.0325,
  "row": {
    "id": 1597,
    "row_number": 1,
    "index_value": "ROW-VEC-001",
    "data": {
      "task_id": "ROW-VEC-001",
      "title": "Define v1 hybrid search product scope"
    },
    "assets": []
  },
  "match": {
    "source": "hybrid",
    "vector_score": 0.91,
    "vector_rank": 2,
    "lexical_rank": 1,
    "point_id": "dataset-row-point-id",
    "chunk_index": 0,
    "content_hash": "content-hash",
    "snippet": "Dataset: Vector Tasks ..."
  }
}
```

The vector database is never canonical. Rowset hydrates results from Postgres
after retrieval and skips stale or inaccessible row ids.

## Accepted Use Cases

- Find exact task IDs, customer names, URLs, and codes that lexical search
  should rank highly.
- Find semantically related rows such as "stale vector cleanup" even when the
  exact words differ.
- Search a known dataset with server-derived tenant and dataset filters.
- Apply canonical Rowset row filters such as `status`, `area`, or other headers.
- Backfill one dataset after enabling vector search or changing embedding model
  settings.
- Let MCP agents retrieve source-linked rows without custom REST wiring.

## Non-Goals

- Public-preview search or using public preview URLs as private access control.
- Cross-dataset, project-wide, workspace-wide, or external app search.
- Rowset-owned Google Sheets sync, dashboard upload wizards, or spreadsheet
  write-back.
- Vector database canonical storage of rows, ACLs, project metadata, or public
  sharing state.
- UI search polish beyond documented API/MCP surfaces.
- Built-in reranking, generated answers, or agent memory beyond row retrieval.
- A second provider implementation before Qdrant search is stable in production.

## Operational Contract

- `ROWSET_VECTOR_SEARCH_ENABLED=False` keeps existing Rowset behavior unchanged.
- Qdrant credentials and embedding provider keys must stay in environment
  configuration and out of docs, logs, screenshots, and final messages.
- Indexing failures are logged and do not roll back canonical writes.
- Search failures return service errors instead of silently returning private or
  cross-tenant results.
- Reindexing is rebuildable from Rowset/Postgres.

## Open Follow-Ups

- Add UI affordances only after API/MCP behavior is stable.
- Add larger quality evaluation datasets once real usage reveals query patterns.
- Consider cross-dataset retrieval after single-dataset search has production
  evidence and clearer ACL semantics.
