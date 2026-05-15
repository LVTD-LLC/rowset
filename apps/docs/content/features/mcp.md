---
title: MCP access
description: Connect AI agents to FileBridge through the hosted MCP endpoint.
keywords: FileBridge MCP, Streamable HTTP MCP, AI agents
---

# MCP access

FileBridge includes a hosted MCP endpoint so compatible AI agents can discover and use datasets without browser automation.

## MCP URL

```text
{{ mcp_url }}
```

## Authentication

Prefer an auth header:

```http
Authorization: Bearer {{ api_key_full }}
```

If your MCP client cannot send bearer headers, use:

```http
X-API-Key: {{ api_key_full }}
```

As a last resort, append the key to the MCP URL:

```text
{{ mcp_url }}?api_key={{ api_key_full }}
```

Prefer headers because URLs are more likely to be copied into logs, screenshots, and shell history.

## First checks

After connecting, call:

```text
get_user_info
```

Then discover datasets with:

```text
get_all_datasets
```

For a specific ready dataset, agents can use:

```text
get_dataset
list_dataset_rows
get_dataset_row
get_dataset_row_by_index
create_dataset_row
update_dataset_row
delete_dataset_row
```

Row tools enforce the same API-key ownership boundary as the REST API. `create`,
`update`, and `delete` change dataset contents, so agents should ask the user before
using them unless the user explicitly requested the change.

For datasets imported from Google Sheets, row changes can also be written back to the
source spreadsheet when the user has explicitly connected Google Sheets access. Basic
Google signup/login does not request Sheets permission. Deployments can also fall back
to `GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON` when the sheet is shared with that service
account as an editor. Public Google Sheets CSV import by itself is read-only.

Use MCP tools for agent workflows when available. If the runtime cannot configure MCP, use the REST API with the same API key.

## Agent setup prompt

The dashboard shows a ready-to-copy prompt for setting up an agent. The same prompt is also shown on the Agent access page so users can copy it from docs.
