---
title: Agent access
description: Configure AI agents to use FileBridge without browser automation.
keywords: FileBridge, agents, MCP, OAuth, SKILL.md
---

# Agent access

FileBridge gives you a short copy/paste setup prompt for trusted AI agents. It includes the hosted MCP URL, REST API base URL, `SKILL.md` instructions URL, and your API key for clients that need bearer-token auth.

The dashboard preview masks the API key. The copy button includes the real key, so treat the copied prompt like a password.

## Copy/paste setup prompt

The docs show a masked example:

```text
{{ agent_setup_prompt_masked }}
```

Use the dashboard copy button when you want the full prompt with the API key included.

## SKILL.md instructions

The prompt links to:

```text
{{ site_url }}/SKILL.md
```

That file gives an agent durable setup instructions for FileBridge MCP and REST fallback. It tells agents how to discover the current tools and API docs instead of hardcoding an endpoint list.

## Recommended agent behavior

- Prefer MCP tools over browser automation.
- Discover current MCP tools and schemas from the connected server before acting.
- For REST fallback, inspect the current API docs from the REST API base.
- Discover datasets before reading rows.
- Inspect one dataset's current metadata before row operations.
- Create or modify data only when the user asks for that change.
- For Google Sheets-backed datasets, row changes may also update the source spreadsheet when the user has explicitly connected Google Sheets access or service-account write-back is configured.
- Use the Dataset API only if MCP configuration is unavailable and the user approves REST API authentication.
- Ask before destructive actions like deleting datasets or rows.
- Keep user data private and never print credentials into public logs or messages.

## Related docs

- MCP access explains the hosted MCP endpoint and auth options.
- API Reference explains REST authentication and endpoints.
- Public previews are for browser sharing, not agent authentication.
