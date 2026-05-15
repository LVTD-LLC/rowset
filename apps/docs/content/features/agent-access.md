---
title: Agent access
description: Configure AI agents to use FileBridge without browser automation.
keywords: FileBridge, agents, MCP, API key, SKILL.md
---

# Agent access

FileBridge gives you a copy/paste setup prompt for AI agents. It includes the hosted MCP URL, REST API base URL, your API key, and the `SKILL.md` instructions URL.

## Copy/paste setup prompt

Paste this into a trusted agent:

```text
{{ agent_setup_prompt }}
```

Treat this prompt like a password because it includes your full API key.

## SKILL.md instructions

The prompt links to:

```text
{{ site_url }}/SKILL.md
```

That file gives an agent durable setup instructions for FileBridge MCP, including the expected tools and safety rules.

## Recommended agent behavior

- Prefer MCP tools over browser automation.
- Verify setup with `get_user_info`.
- Discover available datasets with `get_all_datasets`.
- Inspect one dataset with `get_dataset` before row operations.
- Read rows with `list_dataset_rows`, `get_dataset_row`, or `get_dataset_row_by_index`.
- Modify rows with `create_dataset_row`, `update_dataset_row`, and `delete_dataset_row` only when requested.
- Use the Dataset API if MCP configuration is unavailable.
- Ask before destructive actions like deleting datasets or rows.
- Keep the API key private and never print it back into public logs or messages.

## Related docs

- MCP access explains the hosted MCP endpoint and auth options.
- API Reference explains REST authentication and endpoints.
- Public previews are for browser sharing, not agent authentication.
