---
title: Create datasets
description: Create ready Rowset datasets with stable indexes, instructions, metadata, initial rows, and project placement.
keywords: create Rowset dataset, agent dataset, index column, dataset instructions
updated_at: 2026-11-03
---

# Create datasets

Last updated: November 3, 2026.

Create a dataset when an agent or application needs a stable row store it can
come back to later.

## Before you create one

Decide four things:

- the dataset name
- the headers
- the index column
- the instructions future agents should follow

If there is no reliable business key, omit `index_column` and let Rowset create
`rowset_id`. For the tradeoff, read [Rowset `rowset_id` vs business
keys](/blog/rowset-id-vs-business-keys) before production agents start updating
rows.
If you are choosing between a Rowset-hosted agent dataset and a spreadsheet-style
database workspace, review [NocoDB alternatives for AI-agent-managed
datasets](/blog/nocodb-alternatives) first.

## Create through MCP

Use MCP when a trusted agent is doing the setup. First [connect the
client](/docs/connect-mcp) with an account-wide Read + write or Admin key.
These levels are not per-dataset grants. Complete the
[first-project discovery and confirmation steps](/docs/quickstart) before
creating a dataset for a new workflow; reuse an existing matching dataset.

The examples below are MCP **argument objects**, not complete protocol requests.
They match the [Rowset tool definitions at main 68b4a71](https://github.com/LVTD-LLC/rowset/blob/68b4a71010b8fa532b77af0fedea32c0eab0b356/apps/mcp_server/server.py),
checked November 3, 2026. Check your connected client's live schema and replace
angle-bracket placeholders with returned keys.

### 1. Create the empty schema

Call `create_dataset` with the approved project and section keys. This task
schema has no invented production rows:

```json
{
  "name": "Agent tasks",
  "description": "Tasks delegated to trusted agents",
  "instructions": "Keep task_id stable. Only move status to done when acceptance notes are present.",
  "headers": ["task_id", "status", "next_action", "notes"],
  "index_column": "task_id",
  "column_types": {
    "task_id": "text",
    "status": {"type": "choice", "choices": ["todo", "doing", "blocked", "done"]},
    "next_action": "text",
    "notes": "text"
  },
  "project_key": "<project_key>",
  "section_key": "<section_key>",
  "prevent_duplicate_name": true
}
```

Omit `section_key` if the project has no section. For an intentionally ungrouped
dataset, omit both placement keys and `prevent_duplicate_name`; the duplicate-name
guard requires a project. A duplicate-name error is a reason to inspect the
matching dataset, not disable the guard and create again. Dataset instructions
are guidance: they do not enforce approval or the acceptance-notes rule.

### 2. Inspect the returned dataset key

Save `dataset.key` from the create result, then call `get_dataset`:

```json
{"dataset_key": "<dataset_key>"}
```

The inspection returns dataset context directly. Confirm `key`,
`index_column = task_id`, `index_generated = false`, the headers and
`column_schema`, project placement, instructions, and `row_count = 0`.
A successful create is not proof that a useful row has been saved.

### 3. Save one real task and read it back

Take an actual authorized task from your workflow. Call `create_dataset_row`
with `dataset_key` and a `data` object keyed by these headers; supply its unique,
non-blank `task_id`. Then independently call `get_dataset_row_by_index`:

```json
{"dataset_key": "<dataset_key>", "index_value": "<actual_task_id>"}
```

Confirm `row.data` contains the expected task and next action. The dataset key,
internal row ID, and `task_id` are different identifiers; this lookup uses the
configured index value. If a write times out, inspect that index before retrying.
For exact write arguments, duplicate handling, and safe updates, continue with
[working with rows](/docs/work-with-rows).

## Create through REST

```http
POST {{ api_base_url }}/datasets
Authorization: Bearer {{ api_key_placeholder }}
Content-Type: application/json
```

```json
{
  "name": "Agent tasks",
  "description": "Tasks delegated to trusted agents",
  "instructions": "Only move status to done when acceptance notes are present.",
  "metadata": {
    "status_values": ["todo", "doing", "blocked", "done"]
  },
  "headers": ["task_id", "status", "owner", "next_action", "notes"],
  "index_column": "task_id",
  "column_types": {
    "task_id": "text",
    "status": {
      "type": "choice",
      "choices": ["todo", "doing", "blocked", "done"]
    },
    "owner": "text",
    "next_action": "text",
    "notes": "text"
  },
  "rows": [
    {
      "task_id": "TASK-001",
      "status": "todo",
      "owner": "Rasul",
      "next_action": "Draft the first row",
      "notes": ""
    }
  ]
}
```

Initial creation accepts up to 1,000 rows. Add larger batches after creation
with row endpoints or MCP row tools.

## Put it in a project

If the dataset belongs to a workflow group, include `project_key`. If it belongs
inside a project section, include both `project_key` and `section_key`.

```json
{
  "project_key": "{project_key}",
  "section_key": "{section_key}"
}
```

Projects and sections help with discovery. They do not change who can access the
dataset.

## Good first datasets

- Personal CRM: `people`, indexed by `email` or `person_id`
- Agent task board: `agent_tasks`, indexed by `task_id`
- Feedback triage: `feedback`, indexed by `feedback_id`
- Content pipeline: `content_queue`, indexed by `slug`
- Product catalog: `products`, indexed by `sku`

See [Use cases](/use-cases) for starter shapes.
