---
title: Start with your first agent dataset
description: Connect a trusted AI agent to Rowset and create one useful API-backed dataset.
keywords: Rowset tutorial, getting started, MCP, dataset API
---

# Start with your first agent dataset

This guide connects a trusted agent to Rowset and creates one small dataset the
agent can inspect and update later.

You will use the dashboard for setup, then the agent will use authenticated MCP
or REST for the actual dataset work. Public previews stay off unless you
explicitly ask to share a read-only browser page.

Use this as the shortest path. After it works, use the broader
[dataset guide](/docs/datasets/) when you need projects, relationships, image
columns, exports, or public previews.

## Before you start

You need a Rowset account, a trusted agent runtime, and a private place to store
an API key such as an environment variable or secret store.

## 1. Copy the Rowset setup prompt

Sign in to Rowset and copy the dashboard agent setup prompt.

The docs show a masked example:

```text
{{ agent_setup_prompt_masked }}
```

The dashboard preview masks the API key. The copy button includes the real key,
so treat the copied prompt like a password.

## 2. Store the API key privately

Store the key in the agent runtime as `ROWSET_API_KEY`.

For MCP and REST, Rowset expects a bearer token:

```http
Authorization: Bearer {{ api_key_placeholder }}
```

Use `X-API-Key` only for REST clients that cannot send bearer tokens.

## 3. Connect the MCP server

Configure the agent's MCP client with the hosted Rowset endpoint:

```bash
codex mcp add rowset --url {{ mcp_url }} --bearer-token-env-var ROWSET_API_KEY
```

The command records the env-var name, not the raw key.

## 4. Verify access

Ask the agent to verify the connected account and load the current Rowset
capabilities:

```text
Call get_user_info, then call get_rowset_capabilities.
```

The agent should use MCP tool discovery for exact tool names and input schemas.

## 5. Create one dataset

Ask the agent to create a small dataset with a stable index column. For a first
run, choose a workflow with a natural key:

- `email` for a personal CRM
- `task_id` for an agent task board
- `feedback_id` for feedback triage
- `sku` for a product catalog

If the source has no stable key, ask the agent to let Rowset generate
`rowset_id`.

Example prompt:

```text
Create a Rowset dataset named agent_tasks with headers task_id, status, owner,
next_action, and notes. Use task_id as the index column. Add three example rows
and include instructions that status must be todo, doing, blocked, or done.
```

The agent should call `get_dataset` after creation so it has the dataset key,
headers, index column, instructions, and schema context.

## 6. Try one update

Ask the agent to update a row by index value, then read it back:

```text
Update TASK-001 to status doing, then fetch that row by task_id and summarize
what changed.
```

You now have a private dataset the agent can continue using in later sessions.

## Next steps

- [How Rowset datasets work](/docs/datasets/) for index columns,
  projects, relationships, schema, exports, and previews.
- [Work with rows](/docs/work-with-rows/) for read, search, create, update, and
  delete patterns.
- [Connect over MCP](/docs/connect-mcp/) for a focused MCP setup guide.
- [MCP tool reference](/docs/mcp-tools/) when an agent needs exact tool groups.
- [Use cases](/use-cases/) for starter dataset shapes.
