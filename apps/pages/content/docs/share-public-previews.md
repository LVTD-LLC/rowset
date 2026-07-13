---
title: Share a public preview
description: Share a read-only dataset preview without requiring an API client.
keywords: Rowset public preview, dataset sharing, password protected preview
---

# Share a public preview

Public previews let someone view a read-only dataset page without using the authenticated REST API.

## When to use a public preview

Use public previews for:

- quick review by a teammate or client
- sharing a small live table without building an app
- giving non-technical users a browser-friendly view

Use the authenticated Dataset API instead when a system needs to read or mutate rows programmatically.

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

The response includes the public preview URL.

If the data is not meant for casual forwarding, add a password. Anyone with the link and password can view the preview.

## Security notes

- Public previews are read-only.
- Password protection is optional, but recommended for anything private.
- Disable the preview when the sharing window is over.
- Do not use public previews as an API-auth replacement for agents or applications.

## Public preview vs API

- **Public preview**: browser page, read-only, optional password.
- **Dataset API**: authenticated HTTP endpoints, supports row reads/writes and exports.

## Related docs

- [Dataset API](/docs/dataset-api)
- [MCP tool reference](/docs/mcp-tools)
- [How Rowset datasets work](/docs/datasets)
