---
title: Design dataset schema
description: Use semantic column types, descriptions, choice values, references, metadata, and instructions to make Rowset datasets safer for agents.
keywords: Rowset schema, column types, choice columns, reference columns, dataset instructions
updated_at: 2026-10-31
---

# Design dataset schema

Last updated: October 31, 2026.

Good Rowset datasets are explicit. The goal is not only to store rows, but to
give future agents enough context to read and update the right fields.

If a model produces JSON before an agent writes rows, use the [structured-output
validation guide](/blog/ai-agent-structured-output) to separate schema validity,
business-rule checks, and retry-safe persistence.

## Use semantic column types

Rowset supports these semantic types:

- `text`
- `tags`
- `integer`
- `number`
- `currency`
- `boolean`
- `date`
- `datetime`
- `email`
- `url`
- `choice`
- `image`
- `reference`

Pass a plain string for simple types:

```json
{
  "email": "email",
  "price": "currency"
}
```

Use `tags` when row values should remain comma-separated strings for agents and
API clients but appear as individual pills in Rowset's UI:

```json
{
  "topics": "tags"
}
```

For example, `"Django, HTMX, agents"` is stored and returned unchanged. The UI
trims each segment and ignores empty segments when rendering pills.

Pass an object when the column needs more metadata:

```json
{
  "status": {
    "type": "choice",
    "description": "Current workflow state",
    "choices": ["todo", "doing", "blocked", "done"]
  }
}
```

## Add descriptions where names are ambiguous

Agents should not have to guess whether `owner` means account executive, product
owner, user, assignee, or vendor. Add descriptions for ambiguous fields:

```json
{
  "owner": {
    "type": "text",
    "description": "Person responsible for the next action"
  }
}
```

## Store workflow rules in dataset instructions

Use dataset instructions for rules that should survive across agent sessions:

```text
Only mark a task done when acceptance_notes is non-empty. Keep blocked_reason
filled while status is blocked. Do not delete rows without asking.
```

Use JSON metadata for rules that machines should parse:

```json
{
  "status_values": ["todo", "doing", "blocked", "done"],
  "default_status": "todo"
}
```

The [AI inventory agent guide](/blog/ai-agent-inventory-management) shows a
three-dataset schema for product records, inventory observations, and controlled
action proposals.

## Separate allowed values from allowed actions

A choice column restricts a field's non-blank values. It does not enforce a
workflow transition or the instructions above. Dataset instructions and JSON
metadata give agents context; they are not executable validation policies.

For the task schema above, `status: "done"` is an allowed choice even when
`acceptance_notes` is empty. Your agent or application must check that second
field before sending the write. A blank choice value is also allowed by Rowset;
if your workflow requires a status, enforce that requirement in the caller.

Keep these responsibilities distinct:

| Proposed task update | Rowset choice check | Caller responsibility |
|---|---|---|
| `status: "finished"` | Rejects a value outside the declared choices | Correct the value rather than retrying unchanged |
| `status: ""` | Allows a blank choice | Reject it if status is required for this workflow |
| `status: "done"`, empty `acceptance_notes` | Allows the declared choice | Stop: the completion rule is not satisfied |
| `status: "done"`, non-empty `acceptance_notes` | Allows the declared choice | Verify the evidence and any required approval before writing |

An allowed label is not proof that the work happened. Likewise, a valid Rowset
reference establishes a link to an accessible object, not permission to perform
an external action. Enforce approval in the application or executor; a writable
`approved` field is not an authorization boundary.

For partial updates, read the existing row and check the proposed resulting
record, not only the fields in the patch. Changing the notes could invalidate a
task that is already marked done.

## Put one useful schema into use

Choose a real task and its stable identifier. Have your connected agent inspect
the dataset's current headers, index, choices, and instructions before changing
anything. Agree which checks belong in the caller, then use the
[row-work handoff](/docs/work-with-rows) to find or
save that task and read it back separately. If you have not connected an agent,
start with [private MCP setup](/docs/connect-mcp).

Do not paste a provider's JSON Schema into Rowset column metadata and assume it
will run as a validator. Keep the model-output contract and application checks
separate from the dataset's semantic schema; the
[structured-output guide](/blog/ai-agent-structured-output) covers that boundary.

## Evolve schema in place

Use schema mutation tools when an active dataset needs to change:

```text
add_column
rename_column
drop_column
reorder_columns
update_dataset_column_types
```

Index columns cannot be dropped, and generated index columns cannot be renamed.
Columns used by relationships must be unlinked before destructive schema
changes.

If a generated index no longer fits an active workflow, do not change row identity under running
agents. Use the [business-key migration guide](/blog/migrate-agent-dataset-business-key) to build
a verified old-to-new key map, copy rows into a new dataset, cut over, and preserve rollback.

## Use references for Rowset objects

Use reference columns when a cell points at another Rowset object:

```json
{
  "source_dataset": {
    "type": "reference",
    "target": "dataset"
  },
  "owning_project": {
    "type": "reference",
    "target": "project"
  }
}
```

Reference columns store canonical Rowset keys and validate non-blank values
inside the same account. Archived dataset and project targets remain valid so
historical rows keep their links.
