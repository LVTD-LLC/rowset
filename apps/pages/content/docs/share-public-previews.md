---
title: Share a dataset for read-only access
description: Share a dataset through a browser preview or public JSON API.
keywords: Rowset public preview, dataset sharing, password protected preview
---

# Share a dataset for read-only access

Public sharing gives people a browser preview and gives applications or AI
agents a dedicated read-only JSON API. Both use the same explicit public setting
and optional password.

## When to use a public preview

Use public previews for:

- quick review by a teammate or client
- sharing a small live table without building an app
- giving non-technical users a browser-friendly view
- letting an application or agent retrieve deliberately public rows

Use authenticated REST or MCP when data must remain private or a client needs to
write rows.

## Enable a preview

Ask your agent to call `update_dataset_public_preview`, or call the REST endpoint:

```http
PATCH {{ api_base_url }}/datasets/{dataset_key}/public-preview
Content-Type: application/json
```

```json
{
  "public_enabled": true,
  "public_page_size": 25,
  "public_password": "optional-password"
}
```

The response includes the public preview URL and public key.

If the data is not meant for unrestricted access, add a password. Anyone with
the link and password can view the preview or call the public read API.

## Read the shared dataset as JSON

An unprotected public dataset needs no API key:

```http
GET {{ api_base_url }}/public/datasets/{public_key}
GET {{ api_base_url }}/public/datasets/{public_key}/rows?limit=500&offset=0
```

For a protected dataset, send the password on every request:

```http
X-Rowset-Public-Password: optional-public-password
```

The rows response includes `has_more` and `offset`, so clients can request every
page. See the [Dataset API](/docs/dataset-api) for the complete pagination loop,
filters, and response boundaries.

## Security notes

- Public browser and JSON access are read-only.
- Password protection is optional, but recommended for anything private.
- Disable the preview when the sharing window is over.
- Do not use public access for private data or as a replacement for authenticated writes.

## Public preview vs API

- **Public browser preview**: human-readable table, read-only, optional password.
- **Public Dataset API**: safe metadata and paginated rows, read-only, optional password.
- **Authenticated Dataset API**: private reads, row writes, lookup, exports, assets, and relationships.

## Related docs

- [Dataset API](/docs/dataset-api)
- [MCP tool reference](/docs/mcp-tools)
- [How Rowset datasets work](/docs/datasets)
