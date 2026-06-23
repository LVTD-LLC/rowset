---
title: Agent access
description: Configure AI agents to use Rowset without browser automation.
keywords: Rowset, agents, MCP, API key, SKILL.md
---

# Agent access

Rowset gives signed-in users a short copy/paste setup prompt for trusted AI agents. It includes the hosted MCP URL, REST API base URL, `SKILL.md` instructions URL, the repo skill install command, and an API key for bearer-token auth.

The dashboard preview masks the API key. The copy button includes the real key, so treat the copied prompt like a password.

## Copy/paste setup prompt

The docs show a masked example:

```text
{{ agent_setup_prompt_masked }}
```

Sign in and use the dashboard copy button when you want the full prompt with the API key included.

## Installable SKILL.md

The canonical skill lives in the Rowset repo. The app also serves that same
checked-in file as markdown at:

```text
{{ site_url }}/SKILL.md
```

Agents that support the skills CLI can install it with:

```bash
{{ skill_install_command }}
```

The source text is available at:

```text
{{ skill_source_url }}
```

The skill gives agents durable setup instructions for Rowset MCP and REST fallback. It tells agents how to discover the current tools and API docs instead of hardcoding an endpoint list.

For MCP, store the key in a private environment variable such as
`ROWSET_API_KEY`, then configure the MCP client's bearer-token env var to
`ROWSET_API_KEY`. That makes the client send `Authorization: Bearer <key>`.

For Codex/OpenClaw-compatible clients, the concrete setup command is:

```bash
codex mcp add rowset --url {{ mcp_url }} --bearer-token-env-var ROWSET_API_KEY
```

Set `ROWSET_API_KEY` in the agent's private runtime environment before running
or syncing the client. The command records only the env-var name, not the raw
key.

If a client only supports custom headers, set `Authorization` to `Bearer <key>`.
Use `X-API-Key` only for REST clients that cannot send bearer tokens.

## Recommended agent behavior

- Prefer MCP tools over browser automation.
- Discover current MCP tools and schemas from the connected server before acting.
- For REST fallback, inspect the current API docs from the REST API base.
- Verify setup with `get_user_info`.
- Discover available datasets with `get_all_datasets`.
- Search for a specific dataset or project with `search_datasets` and `search_projects`.
- Create new ready datasets with `create_dataset` when the user asks for an on-the-fly dataset.
- Inspect one dataset with `get_dataset` before row operations.
- Read rows with `list_dataset_rows`, `get_dataset_row`, or `get_dataset_row_by_index`.
- Modify rows with `create_dataset_row`, `update_dataset_row`,
  `update_dataset_row_by_index`, and `delete_dataset_row` only when requested.
- Enable or disable read-only public previews with `update_dataset_public_preview` only when the user asks to share a dataset.
- Archive mistaken datasets with `archive_dataset`, and restore them with `restore_dataset` when recovery is needed.
- Use the Dataset API only if MCP configuration is unavailable and the user approves REST API authentication. The user can copy the API key from Settings.
- Ask before destructive actions like archiving datasets or deleting rows.
- Keep user data private and never print credentials into public logs or messages.

## Related docs

- MCP access explains the hosted MCP endpoint and bearer token setup.
- API Reference explains REST authentication and endpoints.
- Public previews are for browser sharing, not agent authentication.
