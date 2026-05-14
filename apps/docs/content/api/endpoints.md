---
title: API endpoints
description: Use FileBridge dataset endpoints for row CRUD, indexed lookup, and CSV export.
keywords: FileBridge API, dataset API, CSV API, REST endpoints
---

# API endpoints

FileBridge gives every imported dataset a small REST API. Use these endpoints when your app, script, or agent needs to read, update, or export dataset rows.

## Authentication

Prefer the `Authorization` header for private API requests:

```http
Authorization: Bearer {{ api_key_masked }}
```

Query-string API keys are supported only for clients that cannot send headers:

```text
?api_key={{ api_key_masked }}
```

Keep API keys private. Do not paste full keys into public docs, screenshots, client-side code, or shared tickets.

## Dataset routes

Your API base URL is:

```text
{{ api_base_url }}
```

Replace `{dataset_key}` with the dataset key from the dataset page.

```http
GET {{ api_base_url }}/datasets/{dataset_key}/rows
```

List dataset rows.

```http
GET {{ api_base_url }}/datasets/{dataset_key}/rows/by-index?index_value={index_value}
```

Fetch one row by the dataset index column.

```http
POST {{ api_base_url }}/datasets/{dataset_key}/rows
Content-Type: application/json
```

Create a row. Send JSON where keys match the dataset headers.

```http
PATCH {{ api_base_url }}/datasets/{dataset_key}/rows/{row_id}
Content-Type: application/json
```

Update a row by FileBridge row id.

```http
DELETE {{ api_base_url }}/datasets/{dataset_key}/rows/{row_id}
```

Delete a row by FileBridge row id.

```http
GET {{ api_base_url }}/datasets/{dataset_key}/export.csv
```

Export the dataset as CSV.

## Example

```bash
curl \
  -H "Authorization: Bearer {{ api_key_masked }}" \
  "{{ api_base_url }}/datasets/{dataset_key}/rows"
```

## Notes

- Use the index lookup route when your workflow has a stable business key like `sku`, `email`, `slug`, or `external_id`.
- Use row ids for updates and deletes when you already have the FileBridge row id from a list or lookup response.
- Public previews are separate from the authenticated API. Configure public sharing from the dataset settings page.
