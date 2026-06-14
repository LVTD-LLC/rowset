---
title: MCP access
description: Connect AI agents to Rowset through the hosted MCP endpoint.
keywords: Rowset MCP, Streamable HTTP MCP, AI agents
---

# MCP access

Rowset includes a hosted MCP endpoint so compatible AI agents can discover and use datasets without browser automation.

## MCP URL

```text
{{ mcp_url }}
```

## Authentication

Add the MCP URL to a compatible remote MCP client. The client will discover
Rowset's OAuth metadata, generate an authorization link, and open it in your
browser. Sign in to Rowset, approve access, and the MCP client will store the
OAuth token for future MCP requests.

The dashboard setup prompt includes your API key for clients that cannot complete
MCP OAuth. The visible preview masks it, but the copied prompt includes the real key.

For older clients that cannot complete MCP OAuth, a bearer API key is still
accepted as a compatibility path:

```http
Authorization: Bearer {{ api_key_full }}
```

Prefer OAuth when your client supports it because it avoids copying secrets into
configuration files.

## First checks

After connecting, verify the authenticated user/profile with the user-info tool
exposed by the current MCP server, then discover the available dataset tools and
their schemas from your MCP client.

Do not treat this page as the source of truth for tool names or inputs. The MCP
server and the REST API docs describe the current surface.

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
update_dataset_public_preview
```

Dataset and row tools enforce the authenticated user's ownership boundary.
`create_dataset`, `create_dataset_row`, `update_dataset_row`, and `delete_dataset_row`
change dataset contents, so agents should ask the user before using them unless the
user explicitly requested the change.

Use `update_dataset_public_preview` only when the user asks to share a read-only
browser preview. The tool returns the public preview URL.

Use MCP tools for agent workflows when available. If the runtime cannot configure
MCP, use the REST API only after the user approves REST API authentication.

## Agent setup prompt

The dashboard shows a ready-to-copy prompt for setting up an agent. The Agent access
docs show a masked example and point users back to the dashboard copy button for the
full prompt.
