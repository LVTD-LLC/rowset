---
title: Getting started
description: Learn how to upload a file and turn it into a FileBridge API.
keywords: FileBridge, getting started, CSV API
---

# Getting started

FileBridge turns CSVs and operational files into API-backed datasets that apps, scripts, and AI agents can use.

## What to do first

1. Upload a CSV from the dashboard.
2. Review the preview, headers, and sample rows.
3. Choose the index column your workflow uses for lookups.
4. Confirm the import.
5. Use the generated API endpoints, CSV export, hosted MCP access, or optional public preview.

## Your API key

Authenticated docs can show the full key so you can copy it into tools:

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

- **Agent access** explains MCP setup and what to put in an agent `SKILL.md`.
- **API Reference → User API** is the safest first request for testing a key.
- **API Reference → Dataset API** covers row list, lookup, create, update, delete, and CSV export endpoints.
