---
title: Introduction
description: Learn how Rowset API authentication works and where to find generated API docs.
keywords: Rowset API, API authentication, OpenAPI docs
---

# API Reference introduction

Rowset exposes authenticated REST endpoints for account checks, dataset creation,
profile-wide row search, dataset rows, exports, and public preview settings.

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

- **User API** — verify a key and inspect safe profile details.
- **API key management** — create scoped agent keys with an admin key.
- **Dataset API** — search rows, create datasets; list, look up, create, update,
  delete, export rows, and configure public previews.
