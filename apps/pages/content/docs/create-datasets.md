---
title: Create datasets
description: Create ready Rowset datasets with stable indexes, instructions, metadata, initial rows, and project placement.
keywords: create Rowset dataset, agent dataset, index column, dataset instructions
---

# Create datasets

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

Use MCP when a trusted agent is doing the setup:

```text
create_dataset
```

Pass `description`, `instructions`, `metadata`, `headers`, `rows`,
`column_types`, and optionally `project_key` or `section_key`.

After creation, call:

```text
get_dataset
```

That confirms the dataset key, headers, index column, schema, row count, and
context the agent should keep in memory before mutating rows.

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

See [Use cases](/use-cases/) for starter shapes.
