---
title: How Rowset datasets work
description: Understand Rowset datasets, index columns, schema context, relationships, exports, and sharing.
keywords: Rowset datasets, MCP datasets, index columns
---

# How Rowset datasets work

Datasets are the core object in Rowset. Agents create them through MCP or REST,
then use row tools and endpoints to keep them current.

Agents should inspect a dataset with `get_dataset` before row operations. That
response includes headers, index column, semantic column schema, persistent
dataset context, and relationship summaries.

Use this page as the hub for dataset behavior. If you only need endpoint-level
details, go straight to the [Dataset API](/docs/dataset-api/) or
[MCP tool reference](/docs/mcp-tools/).

## Dataset state

Datasets are active when created and remain editable until archived. Archived
datasets keep their rows and schema metadata but are hidden from normal dataset
lists.

## Choosing an index column

Pick the column your apps and agents naturally use to find a row:

- `sku` for product catalogs
- `email` for people/contact lists
- `slug` for content inventories
- `external_id` for synced systems

If the file does not have a stable key, let Rowset generate one.

For a deeper decision checklist, see the guide to
[choosing an index column for agent-managed rows](/blog/choose-index-column-agent-rows).

## Organizing with projects

Use projects to group related datasets by client, workflow, campaign, or agent
task. New datasets are ungrouped by default. Agents can create datasets inside an
existing project or move an existing dataset into one project.

Use sections when a project needs optional sub-grouping. For example, a Rowset
project can have a Blog section with `content-ledger`, `link-inventory`, and
`blog-pages` datasets.

Projects can also carry JSON metadata such as a GitHub repository, Slack thread,
or Notion doc. That metadata is available through the dashboard, REST, and MCP.

Projects and sections are organization metadata only. They do not change
authenticated API or MCP access.

## Linking datasets

Use relationships when one dataset stores the index value for rows in another
dataset. For example, a Personal CRM can use `People.person_id` as the People
index and store that value in `CRM Messages.person_id`.

Relationships are intentionally simple:

- the source column stores the target row's index value
- the target must be another active dataset in the same account
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

The target row must exist before an image can be attached. For MCP, agents read
local image bytes themselves and pass base64 or a data URI to
`attach_image_to_dataset_row`; hosted MCP cannot read a local file path from the
agent's machine.

Rowset validates and normalizes image bytes before storage. Asset `byte_size`
and `checksum` describe the stored Rowset image, so they may differ from the
source file on disk. The thumbnail URL is always a display URL: it returns a
generated thumbnail when one is smaller, otherwise it falls back to the stored
original image.

Image assets appear in the authenticated dataset view and in public previews
when sharing is enabled. Dataset exports include the `asset:{key}` reference so
automated workflows can still use stable row data without embedding binary files
inside CSV, JSONL, XLSX, SQLite, or Parquet exports.

## Audio columns

Use audio columns when a row needs a private audio file, such as an interview
clip, voice note, call recording, or generated audio sample. Create the column
with type `audio`, then attach the audio through MCP or REST.

Row writes should leave audio cells blank. When audio is attached, Rowset stores
the file privately and writes an opaque `asset:{key}` reference into the cell.
Agents should treat that reference as Rowset-managed metadata, not as a URL or
raw audio data.

The target row must exist before audio can be attached. For MCP, agents read
local audio bytes themselves and pass base64 or a data URI to
`attach_audio_to_dataset_row`; hosted MCP cannot read a local file path from the
agent's machine.

Rowset accepts MP3, WAV, M4A, AAC, Ogg, FLAC, and WebM audio files and stores
the bytes privately without transcoding. Audio assets appear in authenticated
dataset views and public previews when sharing is enabled. Dataset exports
include the `asset:{key}` reference rather than embedding binary files.

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

Use public previews when a human needs a browser-friendly, read-only view. Use
the authenticated Dataset API for applications and agents.

## Related docs

- [Start with your first agent dataset](/docs/quickstart/)
- [Create datasets](/docs/create-datasets/)
- [Work with rows](/docs/work-with-rows/)
- [Dataset API](/docs/dataset-api/)
- [Connect over MCP](/docs/connect-mcp/)
- [Archive, export, and troubleshoot](/docs/archive-export-troubleshoot/)
