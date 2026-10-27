---
title: Work with rows
description: Read, search, filter, create, update, and delete Rowset dataset rows through MCP or REST.
keywords: Rowset rows, row CRUD, row search, dataset rows
updated_at: 2026-10-27
---

# Work with rows

Last updated: October 27, 2026.

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

## Save one real row and verify it

Already have a confirmed dataset and a real task, contact, or feedback item to
save? Give your agent the dataset key or URL and that source input. If you have
not connected an agent or chosen a dataset, start with the
[first-dataset quickstart](/docs/quickstart); do not create a second dataset just
to try row operations.

For a dataset with a stable business-key index, use this handoff:

```text
Save the real input I provided in the confirmed dataset. Inspect the dataset
first and preserve its headers, schema, instructions, index, and privacy settings.
Do not invent missing values. Read the exact index before creating a row. If it
already exists, compare it with my input and update only the changes I requested;
report conflicting identity or unclear intent instead of overwriting it.
After the write, fetch the row again by index and compare the stored fields
with my input. If the write response is uncertain, read that index before retrying.
Report whether the row was created, updated, or already matched, and whether
the separate read-back confirmed the requested values.
```

The MCP sequence is `get_dataset`, `get_dataset_row_by_index`, the appropriate
`create_dataset_row` or `update_dataset_row_by_index` call, then a separate
`get_dataset_row_by_index`. Use the live tool schemas: row `data` is keyed by
the dataset's actual headers. A missing-row response permits creation only
after confirming the dataset and index; an authentication or network failure
does not establish that the row is absent. An unchanged row needs no write.

For a generated `rowset_id` index, keep the key returned by a successful create
and use it for later reads and updates. If a standalone create's response is
lost before you receive that key, stop and reconcile the existing rows rather
than blindly creating another. The
[index-column guide](/blog/choose-index-column-agent-rows) explains which identity
path fits your source.

A successful write response alone is not a verified result. If the follow-up
read fails or differs, report verification as incomplete. With no real source
input, leave the dataset empty; do not insert a placeholder or enable a public
preview to prove the connection works.

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
For a worked REST example, follow [pagination and response counts](/docs/dataset-api#list-rows).

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

For retry-prone agent workflows, use a stable index, patch absolute final
values, and read the row after an uncertain response. The
[idempotent AI-agent updates guide](/blog/idempotent-ai-agent-updates) includes
a complete create-or-update and timeout-recovery pattern.
When a row points to another dataset, apply the
[referential-integrity contract](/blog/referential-integrity-ai-agents): verify
the target, write the parent first, store the exact index, and resolve the link
after the mutation.
For cleanup jobs, use the same exact-key contract inside a reversible
[AI data-cleaning workflow](/blog/ai-data-cleaning-agent) that separates raw rows,
proposed changes, approval, and verified publication.
For product and stock workflows, the
[AI inventory agent guide](/blog/ai-agent-inventory-management) applies that contract
to catalogs, source observations, action proposals, and destination read-back.

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
