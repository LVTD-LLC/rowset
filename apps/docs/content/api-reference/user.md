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
    "state": "signed_up",
    "has_active_subscription": true
  }
}
```

The response does **not** include your API key.

## When to use this endpoint

- Check that an integration is authenticated correctly.
- Give an AI agent a low-risk connectivity test before it works with datasets.
- Confirm which Rowset account a key belongs to.
