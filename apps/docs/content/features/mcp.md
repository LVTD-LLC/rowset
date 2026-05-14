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

Use MCP tools for agent workflows when available. If the runtime cannot configure MCP, use the REST API with the same API key.

## Agent setup prompt

The dashboard shows a ready-to-copy prompt for setting up an agent. The same prompt is also shown on the Agent access page so users can copy it from docs.
