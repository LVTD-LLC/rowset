---
title: User API
description: Use the Rowset user endpoint to verify API access and inspect safe profile details.
keywords: Rowset API, user API, profile API
---

# User API

Use the user endpoint to verify an API key and fetch safe account/profile details for the authenticated user.

## Authentication

```http
Authorization: Bearer {{ api_key_placeholder }}
```

Your API base URL is:

```text
{{ api_base_url }}
```

## Get current user

```http
GET {{ api_base_url }}/user
```

Example:

```bash
curl -H "Authorization: Bearer {{ api_key_placeholder }}" "{{ api_base_url }}/user"
```

Example response:

```json
{
  "email": "{{ user_email_placeholder }}",
  "profile": {
    "id": 123,
    "state": "signed_up",
    "has_active_subscription": false,
    "trial_status": "active",
    "trial_started_at": "2026-07-13T10:30:00Z",
    "trial_ends_at": "2026-07-20T10:30:00Z"
  }
}
```

The response does **not** include your API key.

This authenticated request starts the trial if it has not started already. After the trial
ends, authenticated API requests return HTTP `402` with a stable upgrade response:

```json
{
  "code": "TRIAL_EXPIRED",
  "message": "Your Rowset trial has ended. Upgrade to continue using the API, CLI, and MCP.",
  "upgrade_url": "https://rowset.com/pricing",
  "trial_ended_at": "2026-07-20T10:30:00Z"
}
```

The CLI displays this response, including the upgrade link. MCP tool calls return the same
code and upgrade guidance as a non-retryable tool error.

## When to use this endpoint

- Check that an integration is authenticated correctly.
- Give an AI agent a low-risk connectivity test before it works with datasets.
- Confirm which Rowset account a key belongs to.

## Related docs

- [API overview](/docs/api-overview/)
- [Connect over MCP](/docs/connect-mcp/)
- [Dataset API](/docs/dataset-api/)
