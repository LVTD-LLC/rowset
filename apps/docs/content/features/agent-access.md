# Agent access

FileBridge exposes API and hosted MCP access so AI agents can use the app without browser automation.

## REST API user info

Use the profile API key from the app settings page.

```bash
curl "https://your-filebridge-domain.com/api/user?api_key=<FILEBRIDGE_API_KEY>"
```

The endpoint returns safe account/profile details for the authenticated user. It does **not** return the API key.

```json
{
  "id": 1,
  "email": "user@example.com",
  "username": "user@example.com",
  "first_name": "",
  "last_name": "",
  "full_name": "",
  "date_joined": "2026-05-14T00:00:00Z",
  "is_staff": false,
  "is_superuser": false,
  "profile": {
    "id": 1,
    "state": "signed_up",
    "has_active_subscription": false
  }
}
```

## Hosted MCP

The hosted MCP endpoint is available at:

```text
https://your-filebridge-domain.com/mcp/
```

Use one of these API-key authentication options:

- `Authorization: Bearer <FILEBRIDGE_API_KEY>` header
- `X-API-Key: <FILEBRIDGE_API_KEY>` header
- `?api_key=<FILEBRIDGE_API_KEY>` query parameter on the MCP URL
- `api_key` tool argument when a client cannot send headers

The first MCP tool is:

```text
get_user_info
```

It returns the same safe user/profile details as the REST endpoint.

For most hosted clients, configure the MCP server URL and provide the API key as a bearer token if the client supports auth headers. If it does not, use the URL query parameter form:

```text
https://your-filebridge-domain.com/mcp/?api_key=<FILEBRIDGE_API_KEY>
```

Prefer headers over query parameters when the client supports them, because URLs are more likely to be copied into logs or screenshots.
