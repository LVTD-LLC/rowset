---
title: Introduction
description: Learn how FileBridge API authentication works and where to find generated API docs.
keywords: FileBridge API, API authentication, OpenAPI docs
---

# API Reference introduction

FileBridge exposes authenticated REST endpoints for account checks, dataset rows, and CSV exports.

## Base URL

```text
{{ api_base_url }}
```

## Authentication

Use your API key as a bearer token:

```http
Authorization: Bearer {{ api_key_full }}
```

Example request:

```bash
curl -H "Authorization: Bearer {{ api_key_full }}" "{{ api_base_url }}/user"
```

Authenticated docs show your full key so you can copy it into trusted tools. Treat it like a password: do not put it in frontend code, public repos, shared screenshots, or logs.

## Interactive API docs

FileBridge also exposes generated API docs from the backend schema:

[Open generated API docs]({{ api_docs_url }})

Use those generated docs when you want request/response schemas or to inspect lower-level endpoint details. Use this docs section for workflow-oriented guidance.

## Sections

- **User API** — verify a key and inspect safe profile details.
- **Dataset API** — list, look up, create, update, delete, and export dataset rows.
