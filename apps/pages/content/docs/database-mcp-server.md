---
title: Database MCP server decision guide
description: Decide when to connect an agent directly to a database and when to use Rowset as a private dataset backend.
keywords: database MCP server, Rowset MCP, agent database, dataset backend
---

# Database MCP server decision guide

A direct database MCP server is useful when an agent needs controlled access to an existing
production database. Rowset is useful when the agent needs its own private, structured dataset
backend without exposing that database.

If you are choosing the storage architecture before choosing an access path, use the [database for
AI agents decision guide](/blog/database-for-ai-agents). It separates conversation history,
checkpoints, vector retrieval, operational state, artifacts, and audit evidence before comparing
infrastructure.

## The decision

A database MCP server is a bridge into an existing database. It lets an agent inspect tables, run
queries, and sometimes write data. That is a good fit when the task depends on source-of-truth
records, joins, or a mature database permission model.

Rowset is a hosted dataset workspace for trusted agents. The agent can create datasets, choose a
stable index column, add instructions, maintain rows, search, export, and optionally share a
read-only preview. It is a good fit for task boards, feedback queues, personal CRMs, content
pipelines, QA trackers, research tables, and other workflow-shaped data.

## Use a direct database MCP server when

- The agent must query existing transactional or analytical records.
- The database schema is already the right abstraction for the work.
- The data is too large to copy and joins matter.
- You can provide least-privilege credentials, query limits, timeouts, and audit logs.
- Read and write capabilities can be separated, with destructive actions requiring approval.

Even read-only production access can reveal more than intended. Treat direct database access as a
production integration: use narrow grants, document the allowed tables, and avoid unrestricted
credentials in chat sessions.

## Use Rowset when the agent owns the workflow rows

Many agent workflows need durable structure before they need a custom application table. Rowset
gives the agent a private row layer while keeping the dashboard as a human control surface for
setup, review, exports, and optional previews.

A Rowset dataset can carry a description, instructions, semantic column schema, and JSON metadata.
That lets operating rules live with the data across agent runs. The agent should call
`get_dataset` before mutations to recover the current headers, index, and instructions.

Public previews are read-only and off by default. They are for deliberate human review, not for
private programmatic access. Use authenticated [MCP](/docs/connect-mcp) or the
[Dataset API](/docs/dataset-api) for private reads and writes.

## The safest combined pattern

Keep the production database as the source of truth and use Rowset as the agent-managed work layer.
The agent reads an upstream source with an appropriate tool, transforms or summarizes the data,
and writes structured rows into Rowset. Humans can review those rows before a separate,
deterministic process writes anything back to the product system.

For example, a support agent can turn conversations into feedback rows with `feedback_id`,
customer, theme, source URL, status, and next action. A QA agent can maintain a bug ledger with
`issue_id`, severity, reproduction steps, owner, release, and evidence. Neither workflow requires
broad production-database write access.

## Connect Rowset over MCP

Create or copy an agent API key, store it privately in the agent runtime, and configure the hosted
MCP endpoint with a bearer token:

```bash
codex mcp add rowset --url {{ mcp_url }} --bearer-token-env-var ROWSET_API_KEY
```

Get the exact endpoint from the Rowset dashboard or the
[agent access guide](/docs/configure-agent-access). Keep `ROWSET_API_KEY` in an environment variable
or secret store, never in a public prompt, screenshot, shared document, or repository.

Start with one small dataset. Give it a clear name, description, instructions, headers, and stable
index column. Use a business key such as `email`, `task_id`, `feedback_id`, or `sku`; if no reliable
key exists, use the generated `rowset_id` path.

## Recommended first dataset shapes

- **Personal CRM:** `person_id` or `email`, name, company, relationship stage, last interaction,
  next action, and notes.
- **Agent task board:** `task_id`, title, owner, status, priority, blocker, source link, and completion
  evidence.
- **Feedback triage:** `feedback_id`, customer, source, theme, severity, `duplicate_of`, status, and
  next action.
- **Content pipeline:** slug, title, stage, owner, target keyword, brief link, draft link, canonical
  URL, and publish date.
- **QA tracker:** `issue_id`, severity, reproduction notes, environment, owner, fix status, and
  evidence URL.

## Credential and privacy rules

- Store API keys in the runtime or a secret manager and revoke keys that are no longer needed.
- Keep sensitive datasets private; do not put customer data into a public preview.
- Tell the agent which dataset and stable index to use, which statuses are allowed, when to ask
  before changing data, and what counts as done.
- Use private MCP or REST for mutations. Enable read-only previews only when a human audience needs
  them.

## Implementation checklist

1. Decide whether the agent needs existing database state or a new workflow dataset.
2. For database access, prefer a replica, narrow grants, audit logs, query limits, and timeouts.
3. For workflow data, create a Rowset account and copy the agent setup prompt.
4. Store the Rowset key as `ROWSET_API_KEY` in the agent runtime.
5. Connect the hosted MCP endpoint and verify the authenticated user.
6. Create one dataset with a stable index, useful description, and clear instructions.
7. Have the agent call `get_dataset` before row operations.
8. Use private MCP or REST for writes and previews only for intentional human review.
9. Export snapshots when another system needs a deterministic handoff.
10. Promote the workflow to a custom app or database table only after its row shape proves durable.

## Bottom line

Use direct database MCP for controlled access to real source-of-truth tables. Use Rowset when an
agent needs to maintain its own rows, instructions, context, exports, and optional review previews
without touching production data directly. The two approaches can work together: database for the
source of truth, Rowset for agent work.
