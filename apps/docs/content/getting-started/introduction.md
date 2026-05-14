---
title: Getting started
description: Learn how to upload a file and turn it into a FileBridge API.
keywords: FileBridge, getting started, CSV API
---

# Getting started

FileBridge turns CSVs and operational files into API-backed datasets that apps, scripts, and AI agents can use.

## Basic workflow

1. Upload a CSV from the dashboard.
2. Review the preview, headers, and sample rows.
3. Choose the index column your workflow uses for lookups.
4. Confirm the import.
5. Use the generated API endpoints, CSV export, or optional public preview.

## Your API key

Use this key for authenticated API and MCP requests:

```text
{{ api_key_masked }}
```

Prefer sending it as a bearer token:

```http
Authorization: Bearer {{ api_key_masked }}
```

## Your API base URL

```text
{{ api_base_url }}
```

Open any dataset and click **API docs** for endpoint examples that use this base URL.
