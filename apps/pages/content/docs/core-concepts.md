---
title: Core concepts
description: Understand Rowset datasets, rows, indexes, projects, schema, access paths, previews, and exports.
keywords: Rowset concepts, datasets, rows, projects, MCP, REST, public previews
---

# Core concepts

Rowset gives trusted agents and applications a private place to create, inspect,
update, export, and share structured datasets. The product is intentionally
narrow: rows are the source of truth, humans keep ownership, and agents use MCP
or REST instead of browser automation.

## Dataset

A dataset is a private table owned by one Rowset account. It has a name,
headers, rows, an index column, optional description, optional instructions,
JSON metadata, semantic column schema, and sharing/export settings.

Agents should call `get_dataset` before row work. That response includes the
headers, index column, schema, project, instructions, relationship summaries,
asset references, and public preview state needed to avoid guessing.

## Row

A row is one record in an active dataset. Rows can be read, searched, created,
patched, and deleted through MCP or REST. Each row has an internal `row_id`, a
display `row_number`, and an `index_value` from the dataset index column.

Use the index value when a natural business key exists, such as `email`, `sku`,
`slug`, `task_id`, `feedback_id`, or `card_id`.

## Index column

The index column is the stable row identity. If you omit `index_column` when
creating a dataset, Rowset generates a `rowset_id` column so the dataset is
usable immediately.

Stable indexes matter because agents often need to update "this task" or "this
customer" later. Use the [index-column guide](/blog/choose-index-column-agent-rows)
when the right key is not obvious.

## Project and section

Projects group related datasets by workflow, client, campaign, or topic.
Sections optionally group datasets inside one project. They help humans and
agents find the right table, but they do not change authentication boundaries.

Projects and sections can carry JSON metadata, so source links, kickoff threads,
or workflow context can travel with the group.

## Schema and dataset context

Rowset stores semantic column metadata alongside headers. A column can be
`text`, `integer`, `number`, `currency`, `boolean`, `date`, `datetime`, `email`,
`url`, `choice`, `image`, or `reference`.

Use column descriptions when a header is ambiguous. Use dataset instructions for
workflow rules an agent should remember in later sessions.

## MCP and REST

MCP is the preferred path for compatible AI agents because the agent can
discover tools and schemas from the live server. REST is the portable path for
scripts, backend jobs, the Rowset CLI, and clients that cannot use MCP.

MCP, REST, and CLI access use private API keys. When you connect to a
self-hosted instance, create the key on that instance. Public previews are not
an authentication path.

## Public preview

A public preview is a read-only browser page for humans. It can be disabled,
password-protected, and paginated. Use it when a teammate or client needs to
inspect rows without an API client.

Do not use public previews for agents or applications that need private reads or
writes. Use MCP or REST for that.

## Export

Exports create file snapshots for downstream tools. The REST API supports CSV,
JSONL, XLSX, and SQLite exports. The dashboard also offers Parquet where the UI
supports it.

Use row tools for live agent workflows. Use exports when another system expects
a file.
