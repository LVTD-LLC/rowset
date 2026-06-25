---
title: Agent discovery
description: Help AI agents discover Rowset features, tool schemas, skills, and workflow guides.
keywords: Rowset agents, llms.txt, MCP discovery, Rowset skills
---

# Agent discovery

Rowset is designed so agents do not have to rely on stale prompt text. A trusted
agent should discover the live MCP server, then load Rowset's current feature
guide before creating or changing data.

## Recommended startup order

1. Configure the Rowset MCP URL with `Authorization: Bearer <key>`.
2. Discover available MCP tools and schemas from the connected server.
3. Call `get_user_info` to verify authentication.
4. Call `get_rowset_capabilities` to load the current Rowset feature guide.
5. Call `get_all_datasets` or `search_datasets` before creating a new dataset.
6. Call `get_dataset` before row operations so headers, index column, schema
   metadata, dataset context, and relationship summaries are in context.

## MCP capability guide

`get_rowset_capabilities` returns a concise, structured guide for the connected
server. It groups Rowset features by workflow:

- account and MCP setup
- datasets
- dataset context and semantic schema
- schema mutations
- dataset relationships
- projects
- rows
- public previews
- archive, restore, and exports

Use the guide for workflow semantics. Use MCP tool discovery for exact current
input schemas.

## llms.txt

Rowset also publishes a generated text page for agents and search tools:

```text
{{ llms_txt_url }}
```

The page includes the MCP endpoint, REST API base, generated API docs link,
skill URLs, capability groups, use-case guides, and privacy guardrails. It does
not include user API keys or private dataset contents.

## Installable skills

The repo skill package includes three skills:

- `rowset` for setup, MCP authentication, and safe default workflows
- `rowset-features` for explaining supported capabilities
- `rowset-use-cases` for choosing dataset shapes for common workflows

Install them with:

```bash
{{ skill_install_command }}
```

The app serves the skill markdown at:

```text
{{ site_url }}/SKILL.md
{{ features_skill_url }}
{{ use_cases_skill_url }}
```

## What agents should treat as current

- MCP `tools/list` is the exact source for live tool names, descriptions, and
  schemas.
- `get_rowset_capabilities` is the current workflow and feature guide.
- `get_dataset` is the current per-dataset context source before row work.
- Generated API docs are the exact REST schema source.
- Public docs and skills explain stable workflows and guardrails.

## Privacy guardrails

Agents should keep private authenticated access as the default, store keys only
in private environment variables or secret stores, and ask before destructive
actions such as deleting rows, archiving datasets, or clearing preview
passwords.

Public previews are read-only browser sharing. They are not authentication and
do not replace MCP or REST access.
