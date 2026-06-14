---
title: Agent access
description: Configure AI agents to use Rowset without browser automation.
keywords: Rowset, agents, MCP, OAuth, SKILL.md
---

# Agent access

Rowset gives you a short copy/paste setup prompt for trusted AI agents. It includes the hosted MCP URL, REST API base URL, `SKILL.md` instructions URL, and your API key for clients that need bearer-token auth.

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

That file gives an agent durable setup instructions for Rowset MCP and REST fallback. It tells agents how to discover the current tools and API docs instead of hardcoding an endpoint list.

## Recommended agent behavior

- Prefer MCP tools over browser automation.
- Discover current MCP tools and schemas from the connected server before acting.
- For REST fallback, inspect the current API docs from the REST API base.
- Verify setup with `get_user_info`.
- Discover available datasets with `get_all_datasets`.
- Create new ready datasets with `create_dataset` when the user asks for an on-the-fly dataset.
- Inspect one dataset with `get_dataset` before row operations.
- Read rows with `list_dataset_rows`, `get_dataset_row`, or `get_dataset_row_by_index`.
- Modify rows with `create_dataset_row`, `update_dataset_row`, and `delete_dataset_row` only when requested.
- Enable or disable read-only public previews with `update_dataset_public_preview` only when the user asks to share a dataset.
- Use the Dataset API only if MCP configuration is unavailable and the user approves REST API authentication. The user can copy the API key from Settings.
- Ask before destructive actions like deleting datasets or rows.
- Keep user data private and never print credentials into public logs or messages.

## Related docs

- MCP access explains the hosted MCP endpoint and auth options.
- API Reference explains REST authentication and endpoints.
- Public previews are for browser sharing, not agent authentication.
