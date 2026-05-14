---
title: Agent access
description: Configure AI agents and API clients to use FileBridge without browser automation.
keywords: FileBridge, agents, MCP, API key
---

# Agent access

FileBridge exposes REST API and hosted MCP access so AI agents can use your datasets without browser automation.

## REST API user info

Use your profile API key from settings. Your current key is:

```text
{{ api_key_masked }}
```

```bash
curl -H "Authorization: Bearer {{ api_key_masked }}" "{{ api_base_url }}/user"
```

The endpoint returns safe account/profile details for the authenticated user. It does **not** return the API key.

```json
{
  "email": "{{ user_email }}",
  "profile": {
    "state": "signed_up",
    "has_active_subscription": true
  }
}
```

## Hosted MCP

Your hosted MCP endpoint is:

```text
{{ mcp_url }}
```

Use one of these API-key authentication options:

- `Authorization: Bearer {{ api_key_masked }}` header
- `X-API-Key: {{ api_key_masked }}` header
- `?api_key={{ api_key_masked }}` query parameter on the MCP URL
- `api_key` tool argument when a client cannot send headers

The first MCP tool is:

```text
get_user_info
```

For most hosted clients, configure the MCP server URL and provide the API key as a bearer token if the client supports auth headers. If it does not, use the URL query parameter form:

```text
{{ mcp_url }}?api_key={{ api_key_masked }}
```

Prefer headers over query parameters when the client supports them, because URLs are more likely to be copied into logs or screenshots.
