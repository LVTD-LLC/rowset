---
title: Configure agent access
description: Configure AI agents to use Rowset without browser automation.
keywords: Rowset, agents, MCP, API key, SKILL.md
---

# Configure agent access

Rowset gives signed-in users a short copy/paste setup prompt for trusted AI
agents. It includes the current instance's MCP URL, REST API base URL,
`SKILL.md` instructions URL, the repo skill install command, and an API key for
bearer-token auth. On a self-hosted deployment, these URLs are generated from
that instance's configured `SITE_URL`.

The dashboard preview masks the API key. The copy button includes the real key, so treat the copied prompt like a password.

## Copy/paste setup prompt

The docs show a masked example:

```text
{{ agent_setup_prompt_masked }}
```

Sign in and use the dashboard copy button when you want the full prompt with the API key included.

## Choose permissions

When creating an agent API key, choose the smallest permission level that fits
the agent's job:

- **Read** for inspection, exports, and reporting.
- **Read + write** for agents that create or update datasets, rows, projects,
  relationships, or public preview settings.
- **Admin** for trusted automation that needs to create other agent API keys
  through REST or MCP.

## Installable skills

The canonical setup skill lives in the Rowset repo. The app also serves that
same checked-in file as markdown at:

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

The repo also includes two companion skills:

- `rowset-features` for explaining the current Rowset feature surface
- `rowset-use-cases` for concrete dataset patterns such as CRMs, task boards,
  feedback trackers, content pipelines, catalogs, and QA trackers

The app serves those skill files at:

```text
{{ features_skill_url }}
{{ use_cases_skill_url }}
```

Agents and search tools can also read the generated Rowset overview:

```text
{{ llms_txt_url }}
```

For MCP, store the key in a private environment variable such as
`ROWSET_API_KEY`, then configure the MCP client's bearer-token env var to
`ROWSET_API_KEY`. That makes the client send `Authorization: Bearer <key>`.

If you are deciding whether a workflow should start with MCP or REST,
read [When should an AI agent use MCP instead of REST?](/blog/mcp-vs-rest-ai-agents).
In short: use MCP for compatible agent sessions that benefit from discovery, and
use REST for scripts, backend jobs, or constrained runtimes.

For Codex/OpenClaw-compatible clients, the concrete setup command is:

```bash
codex mcp add rowset --url {{ mcp_url }} --bearer-token-env-var ROWSET_API_KEY
```

Set `ROWSET_API_KEY` in the agent's private runtime environment before running
or syncing the client. The command records only the env-var name, not the raw
key.

If a client only supports custom headers, set `Authorization` to `Bearer <key>`.
Use `X-API-Key` only for REST clients that cannot send bearer tokens.

If the agent will use REST instead of MCP, follow
[How to connect an AI agent to the Rowset Dataset API](/blog/connect-ai-agent-to-dataset-api)
for the handoff checklist: scoped key, private secret storage, dataset
inspection, and by-index row operations.

## Recommended agent behavior

- Prefer MCP tools over browser automation.
- Discover current MCP tools and schemas from the connected server before acting.
- Load the current Rowset capability guide with `get_rowset_capabilities`.
- For REST fallback, inspect the current API docs from the REST API base.
- Verify setup with `get_user_info`.
- Discover available datasets with `get_all_datasets`.
- Find archived datasets with `get_archived_datasets` before restoring them.
- Search for a specific dataset or project with `search_datasets` and `search_projects`.
- Create new datasets with `create_dataset` when the user asks for an on-the-fly dataset.
- Inspect one dataset with `get_dataset` before row operations. The response
  includes dataset context, semantic schema, and relationship summaries.
- Read rows with `list_dataset_rows`, `get_dataset_row`, or `get_dataset_row_by_index`.
- Search across datasets with `search_rows` when the relevant dataset is unknown
  or multiple datasets may contain the answer.
- Search inside one dataset with `search_dataset_rows` when vector search is
  enabled and ranked matches are more useful than a paginated row list.
- Modify rows with `create_dataset_row`, `update_dataset_row`,
  `update_dataset_row_by_index`, and `delete_dataset_row` only when requested.
- Enable or disable read-only public previews with `update_dataset_public_preview` only when the user asks to share a dataset.
- Archive mistaken datasets with `archive_dataset`, and restore them with `restore_dataset` when recovery is needed.
- Archive inactive project groups with `archive_project`; this hides the project without archiving its datasets.
- Use the Dataset API only if MCP configuration is unavailable and the user approves REST API authentication. The user can copy the API key from Settings.
- Ask before destructive actions like archiving datasets or deleting rows.
- Keep user data private and never print credentials into public logs or messages.

## Related docs

- [Connect over MCP](/docs/connect-mcp) explains the hosted MCP
  endpoint and bearer token setup.
- [Help agents discover Rowset](/docs/agent-discovery)
  explains `get_rowset_capabilities`, `llms.txt`, and the companion skills.
- [API overview](/docs/api-overview) explains REST authentication.
- [Share a public preview](/docs/share-public-previews) covers
  browser sharing. It is not agent authentication.
