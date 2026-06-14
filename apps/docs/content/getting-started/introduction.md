---
title: Getting started
description: Connect an AI agent to Rowset and create API-backed datasets.
keywords: Rowset, getting started, MCP, dataset API
---

# Getting started

Rowset gives AI agents a stable MCP and REST surface for API-backed datasets.

## What to do first

1. Sign in and copy the dashboard agent prompt.
2. Paste the prompt into a trusted AI agent.
3. Complete the Rowset browser authorization flow when the MCP client asks.
4. Ask the agent to create a dataset from a file, table, or system it can access.
5. Use MCP or REST for row CRUD, CSV export, and optional public previews.

## Your API key

MCP OAuth is the default setup path. Use your API key only with trusted agents or tools that cannot complete remote MCP auth:

```text
{{ api_key_full }}
```

Prefer sending it as a bearer token:

```http
Authorization: Bearer {{ api_key_full }}
```

## Your API base URL

```text
{{ api_base_url }}
```

## Where to go next

- **Working with datasets** explains lifecycle, index columns, and exports.
- **Public previews** explains browser-friendly, read-only sharing through API and MCP.
- **MCP access** explains hosted MCP setup for AI agents.
- **Agent access** gives the copy/paste prompt and `SKILL.md` guidance.
- **API Reference → Introduction** explains REST authentication and links to generated API docs.
- **API Reference → User API** is the safest first request for testing a key.
- **API Reference → Dataset API** covers dataset creation, row CRUD, CSV export, and public preview settings.
