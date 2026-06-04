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

Add the MCP URL to a compatible remote MCP client. The client will discover
FileBridge's OAuth metadata, generate an authorization link, and open it in your
browser. Sign in to FileBridge, approve access, and the MCP client will store the
OAuth token for future MCP requests.

No API key needs to be pasted into the MCP client for the normal setup path.

For older clients that cannot complete MCP OAuth, a bearer API key is still
accepted as a compatibility path:

```http
Authorization: Bearer {{ api_key_full }}
```

Prefer OAuth when your client supports it because it avoids copying secrets into
configuration files.

## First checks

After connecting, call:

```text
get_user_info
```

Then discover datasets with:

```text
get_all_datasets
```

To create a new ready dataset from an agent workflow, call:

```text
create_dataset
```

The tool returns the new dataset key. Agents can use that key immediately with the row tools.

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

Dataset and row tools enforce the authenticated user's ownership boundary.
`create_dataset`, `create_dataset_row`, `update_dataset_row`, and `delete_dataset_row`
change dataset contents, so agents should ask the user before using them unless the
user explicitly requested the change.

For datasets imported from Google Sheets, row changes can also be written back to the
source spreadsheet when the user has explicitly connected Google Sheets access. Basic
Google signup/login does not request Sheets permission. Deployments can also fall back
to `GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON` when the sheet is shared with that service
account as an editor. Public Google Sheets CSV import by itself is read-only.

Use MCP tools for agent workflows when available. If the runtime cannot configure MCP, use the REST API only after the user approves REST API authentication.

## Agent setup prompt

The dashboard shows a ready-to-copy prompt for setting up an agent. The same prompt is also shown on the Agent access page so users can copy it from docs.
