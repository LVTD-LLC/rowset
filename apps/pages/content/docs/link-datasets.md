---
title: Link datasets
description: Connect Rowset datasets with simple relationships and reference columns.
keywords: Rowset relationships, linked datasets, reference columns, dataset links
---

# Link datasets

Use relationships when rows in one dataset point to rows in another dataset.
Use reference columns when a cell points at a Rowset dataset or project object.

## Dataset relationships

A relationship says: this source column stores index values from that target
dataset.

Example:

- `People` is indexed by `person_id`
- `Messages` has a `person_id` column
- a relationship links `Messages.person_id` to `People.person_id`

With enforcement enabled, row writes fail when a non-blank source value does not
match an existing target row index. Blank values are allowed.

## MCP tools

```text
list_dataset_relationships
create_dataset_relationship
resolve_dataset_relationship
delete_dataset_relationship
```

`get_dataset` also includes outgoing and incoming relationship summaries, so an
agent sees links during normal inspection.

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
