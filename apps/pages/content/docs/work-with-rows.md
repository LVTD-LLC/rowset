---
title: Work with rows
description: Read, search, filter, create, update, and delete Rowset dataset rows through MCP or REST.
keywords: Rowset rows, row CRUD, row search, dataset rows
---

# Work with rows

Rows are the working records inside an active dataset. Agents should inspect the
dataset first, then read or change rows using the most stable identifier
available.

## Inspect first

Before row work, call:

```text
get_dataset
```

The response gives the agent the headers, index column, instructions, schema,
project context, relationships, and asset references.

## List rows

Use listing when you know the dataset and need a bounded page:

```text
list_dataset_rows
```

REST:

```http
GET {{ api_base_url }}/datasets/{dataset_key}/rows
```

List rows supports pagination, text query, header filters, sort, and direction.

## Search rows

Use profile-wide search when the relevant dataset is unknown:

```text
search_rows
```

REST:

```http
POST {{ api_base_url }}/search
```

Use dataset search when you know the dataset and want ranked matches:

```text
search_dataset_rows
```

REST:

```http
POST {{ api_base_url }}/datasets/{dataset_key}/search
```

Search uses hybrid vector and lexical retrieval when vector search is enabled.
Rowset/Postgres remains the source of truth.

## Read one row

Prefer index lookup when the dataset has a meaningful key:

```text
get_dataset_row_by_index
```

REST:

```http
GET {{ api_base_url }}/datasets/{dataset_key}/rows/by-index?index_value=TASK-001
```

Use internal row id when you already have it:

```text
get_dataset_row
```

## Create and update rows

Create:

```text
create_dataset_row
```

REST:

```http
POST {{ api_base_url }}/datasets/{dataset_key}/rows
```

Patch by index:

```text
update_dataset_row_by_index
```

REST:

```http
PATCH {{ api_base_url }}/datasets/{dataset_key}/rows/by-index?index_value=TASK-001
```

Patch by row id:

```text
update_dataset_row
```

REST:

```http
PATCH {{ api_base_url }}/datasets/{dataset_key}/rows/{row_id}
```

## Delete rows

Deleting a row is destructive. Agents should ask first unless the user
explicitly requested deletion.

```text
delete_dataset_row
```

REST:

```http
DELETE {{ api_base_url }}/datasets/{dataset_key}/rows/{row_id}
```

For mistaken whole datasets, prefer [archive and restore](/docs/archive-export-troubleshoot)
over deleting row by row.
