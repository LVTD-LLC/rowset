---
title: Dataset API
description: Use FileBridge dataset endpoints for row CRUD, indexed lookup, and CSV export.
keywords: FileBridge API, dataset API, CSV API, REST endpoints
---

# Dataset API

Every imported or API-created dataset gets a small REST API. Use these endpoints when your app, script, or agent needs to create datasets, read/update rows, or export dataset rows.

## Authentication

Prefer the `Authorization` header for private API requests:

```http
Authorization: Bearer {{ api_key_full }}
```

Query-string API keys are supported only for clients that cannot send headers:

```text
?api_key={{ api_key_full }}
```

`X-API-Key: {{ api_key_full }}` is also accepted for clients that support custom headers but not bearer tokens.

Keep API keys private. Authenticated docs can show the full key, but avoid pasting it into public screenshots, logs, client-side code, or shared tickets.

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

Send a dataset name plus `headers`, `rows`, or both. Initial creation accepts up to 1,000 rows; add more rows afterward with the row create endpoint. If `index_column` is omitted, FileBridge adds a generated `filebridge_id` column so the dataset is ready to use immediately.

```json
{
  "name": "Products",
  "headers": ["sku", "name", "price"],
  "index_column": "sku",
  "rows": [
    {"sku": "A-1", "name": "Adapter", "price": "19.99"}
  ]
}
```

The response includes `dataset.key`; use that key with the row endpoints below.

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

Use row ids for updates when you already have the FileBridge row id from a list or lookup response.

## Delete a row

```http
DELETE {{ api_base_url }}/datasets/{dataset_key}/rows/{row_id}
```

Deletes a row by FileBridge row id.

## Export CSV

```http
GET {{ api_base_url }}/datasets/{dataset_key}/export.csv
```

Exports the dataset as CSV.

## Example

```bash
curl \
  -H "Authorization: Bearer {{ api_key_full }}" \
  "{{ api_base_url }}/datasets/{dataset_key}/rows"
```

## Public previews

Public previews are separate from the authenticated API. Configure public sharing from the dataset settings page.
