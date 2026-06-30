---
title: Working with datasets
description: Understand the Rowset dataset lifecycle, index columns, and exports.
keywords: Rowset datasets, MCP datasets, index columns
---

# Working with datasets

Datasets are the core object in Rowset. Agents create them through MCP or REST, then use row tools and endpoints to keep them current.

Agents should inspect a dataset with `get_dataset` before row operations. That
response includes headers, index column, semantic column schema, persistent
dataset context, and relationship summaries.

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

## Linking datasets

Use relationships when one dataset stores the index value for rows in another
dataset. For example, a Personal CRM can use `People.person_id` as the People
index and store that value in `CRM Messages.person_id`.

Relationships are intentionally simple:

- the source column stores the target row's index value
- the target must be another ready dataset in the same account
- blank source values are allowed
- when validation is enabled, row writes fail if a non-blank value does not point
  at an existing target row

Agents can create, list, delete, and resolve relationships through MCP or REST.
`get_dataset` includes outgoing and incoming relationship summaries so agents
can see table links during normal dataset inspection. The dashboard also shows
outgoing and incoming relationships on dataset pages.

## Reference columns

Use reference columns when a cell should point at another Rowset object instead
of storing free text. Set the column type to `reference` and choose a target:

- `{"type": "reference", "target": "dataset"}` stores a Rowset dataset key
- `{"type": "reference", "target": "project"}` stores a Rowset project key

Rowset validates non-blank reference values against objects in the same account
and stores the canonical key. Archived dataset and project targets remain valid
so historical rows keep their links. `get_dataset` groups referenced object
metadata in `dataset_references` and `project_references` by source column and
target key.

## Choice columns

Use experimental choice columns when agents should keep a text value inside a
fixed set. For example, a task board can define `status` with choices like
`Ready to do`, `Doing`, and `Done`.

Choice cells may be blank. When a row includes a non-blank choice value, Rowset
requires it to match one of the configured choices exactly.

## Image columns

Use image columns when a row needs a private visual asset, such as a product
photo, receipt, screenshot, or generated image. Create the column with type
`image`, then attach the image through MCP or REST.

Row writes should leave image cells blank. When an image is attached, Rowset
stores the file privately and writes an opaque `asset:{key}` reference into the
cell. Agents should treat that reference as Rowset-managed metadata, not as a
URL or raw image data.

Image assets appear in the authenticated dataset view and in public previews
when sharing is enabled. Dataset exports include the `asset:{key}` reference so
automated workflows can still use stable row data without embedding binary files
inside CSV, JSONL, XLSX, SQLite, or Parquet exports.

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
