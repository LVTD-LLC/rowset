---
title: Connect over MCP
description: Connect a compatible AI agent to Rowset over MCP.
keywords: Rowset MCP, Streamable HTTP MCP, AI agents, bearer token
---

# Connect over MCP

Use Rowset's MCP server when a trusted agent needs to discover Rowset tools and
work with private datasets without browser automation.

If you are deciding whether your workflow belongs in Rowset, start with
[What is an agent-managed dataset?](/blog/agent-managed-datasets). If you are
choosing between MCP and plain HTTP, read
[When should an AI agent use MCP instead of REST?](/blog/mcp-vs-rest-ai-agents).

## 1. Get the MCP URL

```text
{{ mcp_url }}
```

The Rowset dashboard setup prompt includes this URL and your agent API key.

If you use a self-hosted instance, specify the public URL you expose for it,
including the `/mcp/` path. For example:

```text
https://rowset.example.com/mcp/
```

Create the API key on the same instance you connect to.

## 2. Store the API key

Store the key in a private environment variable such as `ROWSET_API_KEY`, or in
your client's secret store. Do not paste the raw key into public prompts,
screenshots, issue trackers, or repositories.

MCP requests should send:

```http
Authorization: Bearer {{ api_key_placeholder }}
```

## 3. Add the server to the agent client

For Codex/OpenClaw-compatible clients, run:

```bash
codex mcp add rowset --url {{ mcp_url }} --bearer-token-env-var ROWSET_API_KEY
```

The command stores the environment variable name. Make sure the agent runtime
can read the full `ROWSET_API_KEY` value before the client starts.

If your client only supports custom headers, set `Authorization` to
`Bearer {{ api_key_placeholder }}`. Private REST requests use the same bearer
authentication format.

## 4. Verify the connection

Ask the agent to discover the connected server's tools, then call:

```text
get_user_info
get_rowset_capabilities
```

`get_user_info` verifies the authenticated account. A bare
`get_rowset_capabilities` call returns the compact `available_topics` index.
Request specific `topics` for detailed workflow guidance, set
`include_use_cases` only when examples help, or set `full` for the complete
guide.

## 5. Inspect before changing rows

For an existing workflow, ask the agent to discover datasets before creating new
ones:

```text
get_all_datasets
get_archived_datasets
search_datasets
```

Before row operations, the agent should call `get_dataset`. That response
includes headers, index column, dataset instructions, schema metadata, project
context, and relationship summaries.
If you are designing those rules for a new workflow, use the guide to
[structuring dataset instructions for AI
agents](/blog/structure-dataset-instructions-ai-agents).

## 6. Create a small first dataset

When the agent is setting up a new workflow, have it read the relevant use case
first, then create a dataset with a clear `description`, `instructions`, and
stable `index_column`.

Useful starting points:

- [Agent-managed personal CRM](/use-cases/personal-crm)
- [Agent task board](/use-cases/agent-task-board)
- [Feedback triage workflow](/use-cases/feedback-triage)
- [Index-column decision guide](/blog/choose-index-column-agent-rows)
- [Dataset-instructions guide](/blog/structure-dataset-instructions-ai-agents)

## 7. Use the right permission level

Agent API key permissions apply to MCP tools:

- **Read** keys can inspect account details, projects, datasets, rows, and exports.
- **Read + write** keys can also create and update datasets, rows, projects,
  relationships, schema, and public preview settings.
- **Admin** keys can also create new agent API keys through REST or MCP.

Ask before destructive actions such as deleting rows, archiving datasets, or
clearing public preview passwords.

## Direct database MCP servers

Direct database MCP servers are better when an agent must query an existing
Postgres, MySQL, SQLite, or warehouse system and the operator is ready to manage
database credentials, permissions, query cost, and schema safety.

Rowset is narrower. Use it when the agent needs its own private dataset backend
for task boards, CRMs, feedback queues, catalogs, QA trackers, content
pipelines, or similar structured row workflows.
If you are comparing Rowset with open-source database workspaces, read
[Baserow alternatives for AI-agent-managed datasets](/blog/baserow-alternatives).
If your team is choosing between spreadsheet-style backends, see
[NocoDB alternatives for AI-agent-managed datasets](/blog/nocodb-alternatives).

Read [Database MCP server: when to use Rowset instead](/docs/database-mcp-server)
for the longer decision guide.

## Reference

- [MCP tool reference](/docs/mcp-tools)
- [Dataset API](/docs/dataset-api)
- [Configure agent access](/docs/configure-agent-access)
- [Help agents discover Rowset](/docs/agent-discovery)
- [NocoDB alternatives for AI-agent-managed datasets](/blog/nocodb-alternatives)
