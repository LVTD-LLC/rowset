---
title: Link datasets
description: Connect Rowset datasets with simple relationships and reference columns.
keywords: Rowset relationships, linked datasets, reference columns, dataset links
updated_at: 2026-11-02
---

# Link datasets

Last updated: November 2, 2026.

Use relationships when rows in one dataset point to rows in another dataset.
Use reference columns when a cell points at a Rowset dataset or project object.
For a practical modeling guide, read [How to model relationships between
agent-managed datasets](/blog/relationship-modeling-agent-datasets).

## Dataset relationships

A relationship says: this source column stores index values from that target
dataset.

Example:

- `People` is indexed by `person_id`
- `Messages` has a `person_id` column
- a relationship links `Messages.person_id` to `People.person_id`

With enforcement enabled, row writes fail when a non-blank source value does not
match an existing target row index. Blank values are allowed.

Enforcement also blocks deleting a referenced target row or changing its index
while source rows still point to it. Handle the dependent rows explicitly first.
For the parent-first write, read-back, orphan-audit, and deletion workflow, read
[Referential Integrity for AI-Agent Datasets](/blog/referential-integrity-ai-agents).

## MCP tools

```text
list_dataset_relationships
create_dataset_relationship
resolve_dataset_relationship
delete_dataset_relationship
```

`get_dataset` also includes outgoing and incoming relationship summaries, so an
agent sees links during normal inspection.

## Create and resolve your first relationship

Start with two private datasets you are authorized to change. If you have not
connected an agent, follow [MCP setup](/docs/connect-mcp) first. Creating a
relationship needs an account-wide Read + write or Admin key, not a
per-dataset grant.

This fictional example uses `People`, indexed by `person_id`, and `Messages`,
indexed by `message_id`, with a separate `person_id` column. Use the
[row-work guide](/docs/work-with-rows) to save and read back `People.person_id =
P-17`, then a message with `message_id = M-42` and `person_id = P-17`.
Inspect both datasets and list existing relationships before creating one;
reuse a matching definition instead of retrying creation blindly.

The following are MCP **argument objects**, not complete protocol requests.
They match the [current Rowset tool definitions](https://github.com/LVTD-LLC/rowset/blob/edffe0517d384d0d4ad822769ba84acbe6899b33/apps/mcp_server/server.py),
checked November 2, 2026. Replace angle-bracket placeholders with returned
keys and check your connected client's live tool schema.

Call `create_dataset_relationship` on **Messages**, the source dataset:

```json
{
  "dataset_key": "<messages_dataset_key>",
  "source_column": "person_id",
  "target_dataset_key": "<people_dataset_key>",
  "enforce_integrity": true
}
```

Save `relationship.key` from the result. Then call
`resolve_dataset_relationship` with the **message's own index**, not the
person ID:

```json
{
  "dataset_key": "<messages_dataset_key>",
  "relationship_key": "<relationship_key>",
  "source_index_value": "M-42"
}
```

Confirm `source_row.data.message_id` is `M-42`, `target_index_value` is `P-17`,
and `target_row.data.person_id` is `P-17`. A successful response alone is not
enough: a blank source link returns success with no target row. An unenforced
relationship can also return success with a missing target. Inspect the
returned values before using the linked record.

If enforcement rejects existing unmatched values, review those source rows
first. Do not invent people or disable enforcement just to clear the error.
Target existence does not prove the person is the intended one; ambiguous
identity still needs review.

## REST endpoints

```http
GET /api/datasets/{dataset_key}/relationships
POST /api/datasets/{dataset_key}/relationships
GET /api/datasets/{dataset_key}/relationships/{relationship_key}/resolve
DELETE /api/datasets/{dataset_key}/relationships/{relationship_key}
```

## Reference columns

Use a reference column when a row should store a Rowset object key:

```json
{
  "related_dataset": {
    "type": "reference",
    "target": "dataset"
  },
  "project": {
    "type": "reference",
    "target": "project"
  }
}
```

References are useful for metadata, source tracking, and internal Rowset links.
Relationships are better when the cell points to a row in another dataset.
If you are deciding whether to split a workflow into multiple datasets first,
use the [relationship-modeling guide](/blog/relationship-modeling-agent-datasets)
before creating links.
