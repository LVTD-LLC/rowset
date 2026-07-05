---
title: Dataset API
description: Use Rowset dataset endpoints for row CRUD, indexed lookup, archived datasets, exports, and public previews.
keywords: Rowset API, dataset API, CSV API, JSONL API, XLSX API, SQLite API, REST endpoints
---

# Dataset API

Every dataset gets a small REST API. Use these endpoints when your app, script, or agent needs to create datasets, read/update rows, export rows, archive datasets, or configure public preview sharing.

For the product-level concept behind these endpoints, read [What is an
agent-managed dataset?](/blog/agent-managed-datasets). It explains why stable
row identity, schema context, instructions, and authenticated writes matter for
AI-agent workflows.

If you are comparing generic "dataset API" options, Rowset is intentionally
narrow: it gives trusted agents an authenticated row store with stable indexes,
schema context, dataset instructions, metadata, search, exports, and optional
read-only previews. It is not a public spreadsheet embed or a replacement for a
full application database. Use the REST API when a script or app already speaks
HTTP; use [MCP access](/docs/features/mcp/) when an agent can discover tools and
schemas directly. If you are deciding whether an agent should connect directly
to a database or use Rowset as a private dataset layer, read
[Database MCP server: when to use Rowset instead](/playbooks/database-mcp-server).
If you are comparing Airtable-style workspaces for agent-owned rows, read
[Airtable alternatives for AI-agent-managed datasets](/alternatives/airtable).

## Authentication

Prefer the `Authorization` header for private API requests:

```http
Authorization: Bearer {{ api_key_placeholder }}
```

Query-string API keys are supported only for clients that cannot send headers:

```text
?api_key={{ api_key_placeholder }}
```

`X-API-Key: {{ api_key_placeholder }}` is also accepted for clients that support custom headers but not bearer tokens.

Keep API keys private. Copy your real key from Settings or the dashboard agent prompt only when you are configuring a trusted client.

## Base URL

```text
{{ api_base_url }}
```

Replace `{dataset_key}` with the dataset key from the dataset page or from the create-dataset response.

## Create a dataset

```http
POST {{ api_base_url }}/datasets
Content-Type: application/json
```

Send a dataset name plus `headers`, `rows`, or both. Initial creation accepts up to 1,000 rows; add more rows afterward with the row create endpoint. If `index_column` is omitted, Rowset adds a generated `rowset_id` column so the dataset is ready to use immediately. Rowset infers column types from supplied rows; pass `column_types` to override them or add column descriptions for agents.

Use `description`, `instructions`, and `metadata` when an agent should remember
how to use the dataset. For example, a task board can store status rules,
priority conventions, or review steps in dataset metadata instead of requiring
the user to explain them on every run.

To create the dataset inside an existing project, include `project_key`. To place
it inside a project section, include both `project_key` and `section_key`. Omit
both fields to leave the dataset ungrouped.

```json
{
  "name": "Products",
  "description": "Supplier catalog for the agent-managed store",
  "instructions": "Keep sku stable. Treat price as USD unless a row says otherwise.",
  "metadata": {
    "workflow": {
      "status_values": ["draft", "active", "retired"],
      "default_status": "draft"
    }
  },
  "project_key": "{project_key}",
  "section_key": "{section_key}",
  "headers": ["sku", "name", "price"],
  "index_column": "sku",
  "column_types": {
    "sku": {
      "type": "text",
      "description": "Stable supplier SKU used for row lookup"
    },
    "name": "text",
    "price": {
      "type": "currency",
      "description": "Current retail price in USD"
    }
  },
  "rows": [
    {"sku": "A-1", "name": "Adapter", "price": "19.99"}
  ]
}
```

The response includes `dataset.key`; use that key with the row endpoints below. It also returns `column_schema`, including any column descriptions, so agents can keep that context while reading or updating rows.

For agent-managed workflows, prefer a real business key for `index_column` when
one exists: `email` for a personal CRM, `task_id` for an agent task board,
`feedback_id` for feedback triage, or `sku` for a catalog. Stable index values
let agents patch rows by meaning instead of depending on opaque row ids.

Choice columns are experimental. Use them when an agent should keep a text value
inside a fixed set:

```json
{
  "column_types": {
    "status": {
      "type": "choice",
      "description": "Current workflow state for the task",
      "choices": ["Ready to do", "Doing", "Done"]
    }
  }
}
```

Choice cells can be blank. Non-blank row values must match one of the configured
choices exactly.

Reference columns store canonical Rowset keys for objects in the same account.
Use `target: "dataset"` when the cell points at another dataset, or
`target: "project"` when it points at a project:

```json
{
  "column_types": {
    "source_dataset": {
      "type": "reference",
      "target": "dataset"
    },
    "owning_project": {
      "type": "reference",
      "target": "project"
    }
  }
}
```

Reference cells can be blank. Non-blank values must be an owned Rowset key or
matching Rowset URL; Rowset stores the canonical key.

Image columns store private image assets. Create the column with type `image`,
leave image cells blank during row writes, then attach the image with the image
asset endpoint:

```json
{
  "headers": ["sku", "name", "photo"],
  "index_column": "sku",
  "column_types": {
    "sku": "text",
    "name": "text",
    "photo": {
      "type": "image",
      "description": "Primary product photo"
    }
  },
  "rows": [
    {"sku": "A-1", "name": "Adapter", "photo": ""}
  ]
}
```

## Find datasets

```http
GET {{ api_base_url }}/datasets?query=feature&status=ready
```

The dataset list endpoint accepts filters for `query`, `project_key`,
`section_key`, `header_contains`, `status`, and `updated_after`. `query` matches
dataset name, description, instructions, filename, project text, and section
text. `header_contains` should be an exact header name. Accepted `status` values
are `previewed`, `processing`, `ready`, and `failed`. `updated_after` accepts an
ISO 8601 date or datetime; values without a timezone offset, including bare
dates, are interpreted as UTC. For example, `2026-06-01` is treated as
`2026-06-01T00:00:00Z`. Use these filters when an agent needs to find the right
dataset before reading rows or making updates.

## List archived datasets

```http
GET {{ api_base_url }}/datasets/archived
```

Returns archived datasets for the authenticated profile with the same metadata
shape as the normal dataset list. Use this when you need to find a dataset key
before restoring it. Preview-only archived drafts are omitted.

## List rows

```http
GET {{ api_base_url }}/datasets/{dataset_key}/rows
```

Returns the dataset rows.

## Search rows across datasets

```http
POST {{ api_base_url }}/search
Content-Type: application/json
```

Search rows across the authenticated profile with hybrid vector and lexical
retrieval when vector search is enabled. Use this when the relevant dataset is
unknown or when multiple datasets may contain the answer.

```json
{
  "query": "which renewal risks need legal review?",
  "filters": {"status": "Ready"},
  "project_key": "3efc2ad0-8d28-44bc-a554-cb3eab89f45a",
  "archived": false,
  "sort": "rank",
  "limit": 10
}
```

Row filters apply only to datasets that contain those headers. Dataset filters
can restrict by `dataset_key`, `project_key`, `section_key`, `status`, and
`archived`. Each result includes the dataset, canonical row, and match metadata.

## Search rows in one dataset

```http
POST {{ api_base_url }}/datasets/{dataset_key}/search
Content-Type: application/json
```

Search one ready dataset with hybrid vector and lexical retrieval when vector
search is enabled. Use this when you already know the dataset key. Rowset
returns ranked results hydrated from canonical rows; the vector database is only
a retrieval index.

```json
{
  "query": "stale vectors",
  "filters": {"status": "Ready"},
  "limit": 10
}
```

Each result includes the row plus match metadata such as `source`,
`vector_rank`, `lexical_rank`, `vector_score`, `point_id`, `chunk_index`,
`content_hash`, and a short `snippet`.

## Get a row by index

```http
GET {{ api_base_url }}/datasets/{dataset_key}/rows/by-index?index_value={index_value}
```

Use this when your workflow has a stable business key like `sku`, `email`, `slug`, or `external_id`.

## Create a row

```http
POST {{ api_base_url }}/datasets/{dataset_key}/rows
Content-Type: application/json
```

Send JSON where keys match the dataset headers.

## Update a row

```http
PATCH {{ api_base_url }}/datasets/{dataset_key}/rows/{row_id}
Content-Type: application/json
```

Use row ids for updates when you already have the Rowset row id from a list or lookup response.

## Update a row by index

```http
PATCH {{ api_base_url }}/datasets/{dataset_key}/rows/by-index?index_value={index_value}
Content-Type: application/json
```

Use this when your workflow has the dataset's stable index value but not the internal Rowset row id.

## Link datasets

Create a relationship when one dataset column stores another dataset row's index
value. This is useful for simple foreign-key-style workflows such as CRM
messages pointing at people.

```http
POST {{ api_base_url }}/datasets/{dataset_key}/relationships
Content-Type: application/json
```

```json
{
  "name": "Message person",
  "source_column": "person_id",
  "target_dataset_key": "{people_dataset_key}",
  "enforce_integrity": true
}
```

With `enforce_integrity` enabled, non-blank source values must match an existing
target row index when rows are created or updated. Blank values are allowed.

List relationships where a dataset is the source:

```http
GET {{ api_base_url }}/datasets/{dataset_key}/relationships
```

Resolve one source row through a relationship:

```http
GET {{ api_base_url }}/datasets/{dataset_key}/relationships/{relationship_key}/resolve?source_index_value={source_index_value}
```

Delete the relationship definition without changing row data:

```http
DELETE {{ api_base_url }}/datasets/{dataset_key}/relationships/{relationship_key}
```

## Update column types

```http
PATCH {{ api_base_url }}/datasets/{dataset_key}/column-types
Content-Type: application/json
```

Updates semantic column metadata without changing stored row values.

```json
{
  "column_types": {
    "sku": "text",
    "status": {
      "type": "choice",
      "description": "Current workflow state for the task",
      "choices": ["Ready to do", "Doing", "Done"]
    },
    "price": "currency",
    "updated_at": "datetime"
  }
}
```

Supported types are `text`, `choice`, `integer`, `number`, `currency`, `boolean`,
`date`, `datetime`, `email`, `url`, `reference`, and `image`. Pass a metadata
object when a column needs `description`, when a `choice` column needs `type`
and `choices`, when a `reference` column needs `target`, or when an `image`
column needs a description. Reference targets can be `dataset` or `project`.
Updating an existing column to `choice` fails if
stored values are outside the allowed choices. Updating an existing column to
`image` fails unless stored values are blank or existing Rowset asset
references.

## Attach an image

Use the image attach endpoints after the target row exists. The request body
uses base64-encoded JPEG, PNG, or WebP image bytes. You can include a data URI
prefix, but plain base64 is preferred.

Attach by Rowset row id:

```http
POST {{ api_base_url }}/datasets/{dataset_key}/rows/{row_id}/image
Content-Type: application/json
```

Attach by the dataset index value:

```http
POST {{ api_base_url }}/datasets/{dataset_key}/rows/by-index/image?index_value={index_value}
Content-Type: application/json
```

```json
{
  "column_name": "photo",
  "filename": "adapter.png",
  "content_type": "image/png",
  "image_base64": "iVBORw0KGgo..."
}
```

The response includes the updated row and an asset record. The row cell stores
`asset:{key}`. Use the returned `content_url` or `thumbnail_url` with the same
private API authentication when a client needs to fetch the image bytes.

`thumbnail_url` is a display URL for the thumbnail variant. `has_thumbnail`
means Rowset generated a separate smaller thumbnail file. When `has_thumbnail`
is false, the thumbnail variant still responds by falling back to the stored
original image.

Rowset validates and normalizes image bytes before storage. The returned
`byte_size` and `checksum` describe the stored Rowset image, not necessarily the
exact source file bytes sent by the client.

```http
GET {{ api_base_url }}/datasets/{dataset_key}/assets/{asset_key}
GET {{ api_base_url }}/datasets/{dataset_key}/assets/{asset_key}/content?variant=thumbnail
GET {{ api_base_url }}/datasets/{dataset_key}/assets/{asset_key}/content?variant=original
```

To remove an image from a row, patch the image column to an empty string. Rowset
clears the cell and deletes the stored asset for that row and column.

## Update dataset context

```http
PATCH {{ api_base_url }}/datasets/{dataset_key}/metadata
Content-Type: application/json
```

Updates the dataset description, persistent agent instructions, or JSON
metadata without changing rows.

```json
{
  "description": "Launch task board",
  "instructions": "Move blocked tasks back to todo after the blocker is removed.",
  "metadata": {
    "status_order": ["todo", "blocked", "doing", "done"]
  }
}
```

Omit fields you want to keep unchanged. Use an empty string to clear
`description` or `instructions`, and an empty object to clear `metadata`.
Passing `null` leaves that field unchanged.

## Change columns

Use schema mutation endpoints when an agent needs to evolve an existing ready dataset in place.

Add a column and backfill existing rows with a blank or default value:

```http
POST {{ api_base_url }}/datasets/{dataset_key}/columns
Content-Type: application/json
```

```json
{
  "name": "visibility_level",
  "default_value": "internal",
  "column_type": {
    "type": "choice",
    "description": "Controls whether this row can be shared outside the team",
    "choices": ["internal", "shared"]
  }
}
```

Rename a column while preserving row values:

```http
POST {{ api_base_url }}/datasets/{dataset_key}/columns/rename
Content-Type: application/json
```

```json
{
  "old_name": "name",
  "new_name": "full_name"
}
```

Drop a non-index column:

```http
POST {{ api_base_url }}/datasets/{dataset_key}/columns/drop
Content-Type: application/json
```

```json
{
  "name": "notes"
}
```

Reorder columns for display and export:

```http
POST {{ api_base_url }}/datasets/{dataset_key}/columns/reorder
Content-Type: application/json
```

```json
{
  "headers": ["sku", "name", "visibility_level", "price"]
}
```

Reorder requests must include every current header exactly once. Index columns cannot be dropped, and generated index columns cannot be renamed.

## Update project

```http
PATCH {{ api_base_url }}/datasets/{dataset_key}/project
Content-Type: application/json
```

Attach a dataset to one project:

```json
{
  "project_key": "{project_key}"
}
```

Attach it to a section inside the project:

```json
{
  "project_key": "{project_key}",
  "section_key": "{section_key}"
}
```

Detach it from a project:

```json
{
  "project_key": null
}
```

## Update public preview

```http
PATCH {{ api_base_url }}/datasets/{dataset_key}/public-preview
Content-Type: application/json
```

Enable or disable the read-only public preview link. Public previews can only be enabled for ready datasets.

```json
{
  "public_enabled": true,
  "public_page_size": 25,
  "public_password": "optional-password"
}
```

To remove an existing preview password:

```json
{
  "public_enabled": true,
  "clear_public_password": true
}
```

The response includes `dataset.public_url` when `dataset.public_enabled` is true.
When public preview sharing is disabled, `dataset.public_url` is `null`.

## Archive a dataset

```http
DELETE {{ api_base_url }}/datasets/{dataset_key}
```

Archives a dataset without deleting rows or schema metadata. Archived datasets disappear from normal dataset and project lists, public previews are disabled, and the dataset can be restored by key.

## Restore a dataset

```http
POST {{ api_base_url }}/datasets/{dataset_key}/restore
```

Restores an archived dataset to normal dataset and project lists. Restoring does not automatically re-enable a public preview.

## Delete a row

```http
DELETE {{ api_base_url }}/datasets/{dataset_key}/rows/{row_id}
```

Deletes a row by Rowset row id.

## Export a snapshot

```http
GET {{ api_base_url }}/datasets/{dataset_key}/export.csv
```

Exports the dataset as CSV.

```http
GET {{ api_base_url }}/datasets/{dataset_key}/export.jsonl
```

Exports one JSON object per line.

```http
GET {{ api_base_url }}/datasets/{dataset_key}/export.xlsx
```

Exports a spreadsheet workbook.

```http
GET {{ api_base_url }}/datasets/{dataset_key}/export.sqlite
```

Exports a SQLite database with a `rows` table.

## Example

```bash
curl \
  -H "Authorization: Bearer {{ api_key_placeholder }}" \
  "{{ api_base_url }}/datasets/{dataset_key}/rows"
```

## Public previews

Public previews are separate from authenticated row APIs. Use `PATCH /datasets/{dataset_key}/public-preview` or the MCP `update_dataset_public_preview` tool to configure sharing.
