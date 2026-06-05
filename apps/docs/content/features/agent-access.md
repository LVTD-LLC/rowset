---
title: Agent access
description: Configure AI agents to use FileBridge without browser automation.
keywords: FileBridge, agents, MCP, OAuth, SKILL.md
---

# Agent access

FileBridge gives you a copy/paste setup prompt for AI agents. It includes the hosted MCP URL, REST API base URL, and the `SKILL.md` instructions URL. The agent connects to MCP with browser-based OAuth, so the prompt does not include your API key.

## Copy/paste setup prompt

Paste this into a trusted agent:

```text
{{ agent_setup_prompt }}
```

When the MCP client opens the FileBridge authorization link, sign in and approve access in the browser.

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
- Create new ready datasets with `create_dataset` when the user asks for an on-the-fly dataset.
- Inspect one dataset with `get_dataset` before row operations.
- Read rows with `list_dataset_rows`, `get_dataset_row`, or `get_dataset_row_by_index`.
- Modify rows with `create_dataset_row`, `update_dataset_row`, and `delete_dataset_row` only when requested.
- For Google Sheets-backed datasets, row changes may also update the source spreadsheet when the user has explicitly connected Google Sheets access or service-account write-back is configured.
- Use the Dataset API only if MCP configuration is unavailable and the user approves REST API authentication.
- Ask before destructive actions like deleting datasets or rows.
- Keep user data private and never print credentials into public logs or messages.

## Related docs

- MCP access explains the hosted MCP endpoint and auth options.
- API Reference explains REST authentication and endpoints.
- Public previews are for browser sharing, not agent authentication.
