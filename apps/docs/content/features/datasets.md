---
title: Working with datasets
description: Understand the Rowset dataset lifecycle, index columns, and exports.
keywords: Rowset datasets, MCP datasets, index columns
---

# Working with datasets

Datasets are the core object in Rowset. Agents create them through MCP or REST, then use row tools and endpoints to keep them current.

## Dataset lifecycle

1. **Ready** — API-created datasets are available immediately.
2. **Processing** — Legacy background imports may still finish asynchronously.
3. **Failed** — A background import stopped because its stored source could not be parsed or validated.

## Choosing an index column

Pick the column your apps and agents naturally use to find a row:

- `sku` for product catalogs
- `email` for people/contact lists
- `slug` for content inventories
- `external_id` for synced systems

If the file does not have a stable key, let Rowset generate one.

## Organizing with projects

Use projects to group related datasets by client, workflow, campaign, or agent
task. New datasets are ungrouped by default. Agents can create datasets inside an
existing project or move an existing dataset into one project.

Projects can also carry JSON metadata such as a GitHub repository, Slack thread,
or Notion doc. That metadata is available through the dashboard, REST, and MCP.

Projects are organization metadata only. They do not change authenticated API or
MCP access.

## Choice columns

Use experimental choice columns when agents should keep a text value inside a
fixed set. For example, a task board can define `status` with choices like
`Ready to do`, `Doing`, and `Done`.

Choice cells may be blank. When a row includes a non-blank choice value, Rowset
requires it to match one of the configured choices exactly.

## Column descriptions

Add column descriptions when a header needs extra context that should travel
with the dataset. Rowset returns descriptions in `column_schema` through REST and
MCP, and the authenticated dashboard keeps them hidden until someone hovers over
a column name. Public previews do not expose column descriptions.

Use descriptions for conventions an agent should not guess, such as whether
`owner` means the account executive, the product team, or the external customer.

## Exports

Use exports when a workflow needs a full snapshot instead of row-by-row API access.
For automated systems, prefer MCP or the Dataset API unless the consumer
explicitly expects a file.

- `CSV` is the most portable table format.
- `JSONL` is useful for agents, scripts, and streaming-style processing.
- `XLSX` is useful when a teammate needs a spreadsheet file.
- `SQLite` is useful when a local tool needs a queryable database file.
- `Parquet` is useful for analytics tools from the dashboard export menu.

## Sharing

Use Public previews when a human needs a browser-friendly, read-only view. Use the authenticated Dataset API for applications and agents.
