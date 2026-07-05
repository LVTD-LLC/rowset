---
title: Get started
description: Connect a trusted AI agent to Rowset and create your first API-backed dataset.
keywords: Rowset, getting started, MCP, dataset API
---

# Get started

In this tutorial, you will connect a trusted AI agent to Rowset and have it
create one small API-backed dataset. By the end, the agent will have a private
MCP or REST surface it can use for row operations, exports, and optional
read-only previews.

## Create the first dataset

1. Sign in and copy the dashboard agent prompt.
2. Paste the prompt into a trusted AI agent.
3. Store the agent API key in a private `ROWSET_API_KEY` environment variable or client secret store.
4. Configure the MCP client's bearer-token env var to `ROWSET_API_KEY`.
5. Ask the agent to create a dataset from a file, table, or system it can access.
6. Use MCP or REST for row CRUD, exports, and optional public previews.

## API key setup

Use an API key only with trusted agents or tools. After signing in, copy your key from Settings or from the dashboard agent prompt.

```text
{{ api_key_placeholder }}
```

For MCP and REST, prefer sending it as a bearer token:

```http
Authorization: Bearer {{ api_key_placeholder }}
```

For MCP clients with a bearer-token env-var field, store the key as
`ROWSET_API_KEY` and set that field to `ROWSET_API_KEY`. For REST clients that
cannot send bearer tokens, `X-API-Key` is accepted as a fallback.

## Your API base URL

```text
{{ api_base_url }}
```

## Where to go next

- [Connect MCP](/docs/how-to-guides/connect-mcp/) shows the hosted MCP setup path.
- [Configure agent access](/docs/how-to-guides/configure-agent-access/) shows
  the copy/paste prompt, skill URLs, and API key permissions.
- [Work with datasets](/docs/how-to-guides/work-with-datasets/) explains index
  columns, projects, relationships, semantic columns, and exports.
- [Share a public preview](/docs/how-to-guides/share-public-preview/) explains
  browser-friendly, read-only sharing through API and MCP.
- [REST API](/docs/reference/rest-api/) explains REST authentication and links
  to generated API docs.
- [User API](/docs/reference/user-api/) is the safest first request for testing a key.
- [Dataset API](/docs/reference/dataset-api/) covers dataset creation, row CRUD,
  exports, and public preview settings.
