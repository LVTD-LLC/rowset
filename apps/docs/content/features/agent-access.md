---
title: Agent access
description: Configure AI agents and API clients to use FileBridge without browser automation.
keywords: FileBridge, agents, MCP, API key, SKILL.md
---

# Agent access

FileBridge exposes REST API and hosted MCP access so AI agents can use your datasets without browser automation.

## Recommended agent setup

For coding agents, add a short `SKILL.md` or equivalent tool note in the agent workspace that includes:

- Your FileBridge base URL: `{{ api_base_url }}`
- Your API key: `{{ api_key_full }}`
- The expected auth header: `Authorization: Bearer {{ api_key_full }}`
- Links to the relevant API Reference pages inside FileBridge docs

Keep the instructions focused on what the agent should do: authenticate with headers, use the dataset API for reads/writes, and avoid scraping the UI unless explicitly asked.

## Hosted MCP

Your hosted MCP endpoint is:

```text
{{ mcp_url }}
```

Use one of these API-key authentication options:

```http
Authorization: Bearer {{ api_key_full }}
```

```http
X-API-Key: {{ api_key_full }}
```

When a client cannot send headers, use the URL query parameter form:

```text
{{ mcp_url }}?api_key={{ api_key_full }}
```

Prefer headers over query parameters when the client supports them, because URLs are more likely to be copied into logs or screenshots.

## First MCP tool

```text
get_user_info
```

It returns the same safe user/profile details as the User API endpoint.

## REST connectivity check

Before giving an agent dataset-write permissions, have it verify the key with the User API:

```bash
curl -H "Authorization: Bearer {{ api_key_full }}" "{{ api_base_url }}/user"
```

See the API Reference for full endpoint details.
