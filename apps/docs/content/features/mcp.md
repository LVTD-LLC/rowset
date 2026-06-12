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

Dataset and row tools enforce the authenticated user's ownership boundary. Tools
that create, update, or delete data change dataset contents, so agents should ask
the user before using them unless the user explicitly requested the change.

For datasets imported from Google Sheets, row changes can also be written back to the
source spreadsheet when the user has explicitly connected Google Sheets access. Basic
Google signup/login does not request Sheets permission. Deployments can also fall back
to `GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON` when the sheet is shared with that service
account as an editor. Public Google Sheets CSV import by itself is read-only.

Use MCP tools for agent workflows when available. If the runtime cannot configure
MCP, use the REST API only after the user approves REST API authentication.

## Agent setup prompt

The dashboard shows a ready-to-copy prompt for setting up an agent. The Agent access
docs show a masked example and point users back to the dashboard copy button for the
full prompt.
