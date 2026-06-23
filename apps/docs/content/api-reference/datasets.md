---
title: Dataset API
description: Use Rowset dataset endpoints for row CRUD, indexed lookup, exports, and public previews.
keywords: Rowset API, dataset API, CSV API, JSONL API, XLSX API, SQLite API, REST endpoints
---

# Dataset API

Every dataset gets a small REST API. Use these endpoints when your app, script, or agent needs to create datasets, read/update rows, export rows, archive datasets, or configure public preview sharing.

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

Send a dataset name plus `headers`, `rows`, or both. Initial creation accepts up to 1,000 rows; add more rows afterward with the row create endpoint. If `index_column` is omitted, Rowset adds a generated `rowset_id` column so the dataset is ready to use immediately. Rowset infers column types from supplied rows; pass `column_types` to override them.

To create the dataset inside an existing project, include `project_key`. Omit it
to leave the dataset ungrouped.

```json
{
  "name": "Products",
  "project_key": "{project_key}",
  "headers": ["sku", "name", "price"],
  "index_column": "sku",
  "column_types": {"sku": "text", "name": "text", "price": "currency"},
  "rows": [
    {"sku": "A-1", "name": "Adapter", "price": "19.99"}
  ]
}
```

The response includes `dataset.key`; use that key with the row endpoints below.

## Find datasets

```http
GET {{ api_base_url }}/datasets?query=feature&status=ready
```

The dataset list endpoint accepts filters for `query`, `project_key`,
`header_contains`, `status`, and `updated_after`. `header_contains` should be an
exact header name. Accepted `status` values are `previewed`, `processing`,
`ready`, and `failed`. `updated_after` accepts an ISO 8601 date or datetime;
datetime values without a timezone offset are interpreted as UTC. Use these
filters when an agent needs to find the right dataset before reading rows or
making updates.

## List rows

```http
GET {{ api_base_url }}/datasets/{dataset_key}/rows
```

Returns the dataset rows.

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
    "price": "currency",
    "updated_at": "datetime"
  }
}
```

Supported types are `text`, `integer`, `number`, `currency`, `boolean`, `date`, `datetime`, `email`, and `url`.

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
  "column_type": "text"
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

The response includes `dataset.public_url`.

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
