---
title: Configure agent access
description: Configure AI agents to use Rowset without browser automation.
keywords: Rowset, agents, MCP, API key, SKILL.md
---

# Configure agent access

Rowset gives signed-in users a short copy/paste setup prompt for trusted AI
agents. It includes the current instance's MCP URL, REST API base URL, CLI
guide, live documentation and capability resources, setup skill instructions,
and an API key for bearer-token auth. On a self-hosted deployment, these URLs
are generated from that instance's configured `SITE_URL`.

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

The canonical `rowset-setup` skill lives in the Rowset repo. The app serves that
checked-in file as markdown at:

```text
{{ setup_skill_url }}
```

Agents that support the skills CLI can install it with:

```bash
{{ skill_install_command }}
```

The setup skill source text is available at:

```text
{{ setup_skill_source_url }}
```

The setup skill gives agents durable, interface-neutral instructions for MCP,
CLI, and REST. It covers interface selection, credential handling,
authentication verification, first-workflow suggestions, and the optional
agent-account tips automation.

The repo also includes three companion skills:

- `rowset` for ongoing platform interaction and safety rules
- `rowset-features` for explaining the current Rowset feature surface
- `rowset-use-cases` for concrete dataset patterns such as CRMs, task boards,
  feedback trackers, content pipelines, catalogs, and QA trackers

The app serves those skill files at:

```text
{{ site_url }}/SKILL.md
{{ features_skill_url }}
{{ use_cases_skill_url }}
```

Agents and search tools can also read the generated Rowset overview:

```text
{{ llms_txt_url }}
```

The agent should compare the available interfaces with its runtime and the
user's workflow, explain one recommendation, and ask which path to configure:

- MCP for runtimes that support remote MCP and benefit from live tool discovery.
- CLI for terminal workflows, scripts, and local file handling.
- REST for applications and runtimes that already work naturally with HTTP.

After the user chooses, follow the current interface guide and store the key in
a private environment variable such as `ROWSET_API_KEY` or an equivalent secret
store. MCP and REST use `Authorization: Bearer <key>`; the CLI reads the same
key from its private runtime environment.

Make authenticated user-info the final setup action: `get_user_info` over MCP,
`rowset user info` through the CLI, or `GET /api/user` through REST. That request
verifies the connection and completes onboarding. MCP reads and API-key creation
stay trial-neutral, so the MCP trial starts on the first dataset or project mutation;
CLI and REST user-info requests start it immediately.

After verification, the setup prompt asks the agent to use context it already
has about the user's work and read-only Rowset discovery to propose a few useful
project, section, and dataset structures. The agent asks which option to create
before changing data. In runtimes with scheduled tasks, it also offers a
separate opt-in daily Rowset tips automation; that automation runs in the agent
account, not in Rowset.

## Recommended agent behavior

- Recommend MCP, CLI, or REST for the current context and ask before configuring it.
- Discover current capabilities and exact operations through the selected interface.
- Use a bare `get_rowset_capabilities` call, `rowset capabilities` command, or
  `/api/capabilities` request for the compact topic index, then request only the
  relevant topics. Opt into use cases only when useful; use full mode for the
  complete guide.
- Make authenticated user-info the final setup action.
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
