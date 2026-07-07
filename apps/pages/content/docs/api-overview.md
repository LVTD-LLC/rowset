---
title: API overview
description: Learn how Rowset API authentication works and where to find generated API docs.
keywords: Rowset API, API authentication, OpenAPI docs
---

# API overview

Rowset exposes authenticated REST endpoints for account checks, dataset creation,
profile-wide row search, dataset rows, projects, schema changes, image assets,
exports, and public preview settings.

## Base URL

```text
{{ api_base_url }}
```

## Authentication

Use your API key as a bearer token. After signing in, copy your key from Settings or from the dashboard agent prompt.

```http
Authorization: Bearer {{ api_key_placeholder }}
```

For MCP clients, store the key in a private env var such as `ROWSET_API_KEY` and
set the client's bearer-token env-var field to `ROWSET_API_KEY`.

REST clients that cannot send bearer tokens can use `X-API-Key: {{ api_key_placeholder }}` or the `api_key` query parameter.

Example request:

```bash
curl -H "Authorization: Bearer {{ api_key_placeholder }}" "{{ api_base_url }}/user"
```

Treat API keys like passwords: do not put them in frontend code, public repos, shared screenshots, or logs.

## API key permissions

Agent API keys can be created with one of three permission levels:

- **Read** can inspect account details, projects, datasets, rows, and exports.
- **Read + write** can also create and update projects, datasets, rows, relationships, and public preview settings.
- **Admin** includes read/write access and can create new agent API keys through REST or MCP.

Use an admin key only for trusted automation that needs to provision other keys.

## Interactive API docs

Rowset also exposes generated API docs from the backend schema:

[Open generated API docs]({{ api_docs_url }})

Use those generated docs when you want request/response schemas or to inspect lower-level endpoint details. Use this docs section for workflow-oriented guidance.

## Sections

Most users only need three docs in this reference section:

- [Dataset API](/docs/dataset-api/) for creating datasets, searching rows,
  updating schema, linking datasets, attaching image assets, exporting
  snapshots, and managing public previews.
- [MCP tool reference](/docs/mcp-tools/) for the equivalent agent-facing tool
  groups.
- [Configure agent access](/docs/configure-agent-access/) for API-key
  permissions, installable skills, and safe setup prompts.

Use the smaller endpoint pages only when you need a narrow lookup:
[User API](/docs/user-api/) verifies a key and profile details, while
[Project API](/docs/project-api/) covers projects and sections.

## Related docs

- [Connect over MCP](/docs/connect-mcp/) for agent-native tool access.
- [Dataset API](/docs/dataset-api/) for dataset and row endpoints.
- [MCP tool reference](/docs/mcp-tools/) for MCP tool groups.
