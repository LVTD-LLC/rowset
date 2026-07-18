---
title: MCP tool reference
description: Look up Rowset MCP tool groups, startup checks, dataset operations, and safety rules.
keywords: Rowset MCP tools, MCP reference, Rowset agent tools
---

# MCP tool reference

This page is a reference for the Rowset MCP surface. Use [Connect over
MCP](/docs/connect-mcp) when you need setup steps.

Do not treat this page as the exact schema source. The connected MCP server's
tool discovery response is the source of truth for live tool names, descriptions,
and input schemas.

## Startup tools

Use these tools at the beginning of an agent session:

```text
get_user_info
get_rowset_capabilities
```

`get_user_info` verifies the authenticated Rowset account. A bare
`get_rowset_capabilities` call returns a compact `available_topics` index. Pass
only the topic IDs needed for detailed feature groups, MCP tools, REST paths,
and guidance:

```json
{"topics": ["rows", "schema"]}
```

Add `"include_use_cases": true` only when examples help. Use `{"full": true}`
for the complete guide; `full` cannot be combined with `topics`.

## Dataset discovery

Use these tools before creating a new dataset:

```text
get_all_datasets
get_archived_datasets
search_datasets
```

These discovery tools return compact cards for selection. After choosing a
dataset, call `get_dataset` to load headers, index configuration, semantic
schema, instructions, metadata, relationships, and preview settings.

Collection tools return 10 items by default and accept an explicit `limit` up
to 100. While `has_more` is `true`, increase `offset` by the number of entries
in the returned collection array, such as the length of `rows` or `datasets`.
Project detail omits sections; call `get_project_sections` for their paginated
collection.

Use `search_rows` when the relevant dataset is unknown or multiple datasets may
contain the answer:

```text
search_rows
```

When vector search is enabled, `search_rows` accepts natural-language search
text, dataset or project filters, row field filters, archived filtering, sort,
and limit. Results are hydrated from Rowset rows and include match metadata such
as source, ranks, scores, point id, chunk index, and content hash. Rowset/Postgres
remains the source of truth.

## Project tools

Use projects to group related datasets by workflow, client, campaign, or agent
task. Sections provide optional grouping inside a project.

```text
get_all_projects
search_projects
create_project
get_project
get_project_sections
create_project_section
update_project
update_project_metadata
update_project_section
archive_project_section
archive_project
```

Archiving a project hides the project from normal project discovery. It does not
delete or archive its datasets.

Use project metadata for source links, kickoff threads, planning docs, or other
JSON context that should stay with the project. Pass an empty object to
`update_project_metadata` to clear it. Passing an empty string for
`description` to `update_project` clears the project description.

## Dataset tools

Use `create_dataset` when the agent needs a new dataset:

```text
create_dataset
```

Pass `description`, `instructions`, or `metadata` when the dataset should carry
persistent operating context for future agent runs. Pass `project_key` to create
the dataset inside a project, or pass both `project_key` and `section_key` to
place it inside a project section.

For a specific active dataset, use:

```text
get_dataset
list_dataset_rows
search_dataset_rows
get_dataset_row
get_dataset_row_by_index
create_dataset_row
update_dataset_row
update_dataset_row_by_index
delete_dataset_row
archive_dataset
restore_dataset
```

`get_dataset` returns dataset context, semantic column schema, and relationship
summaries. Agents should call it before row operations.

Dataset and row tools enforce the authenticated user's ownership boundary.
`create_dataset`, row mutation tools, and schema mutation tools change dataset
contents, so agents should ask the user before using them unless the user
explicitly requested the change.

Use `archive_dataset` when the user asks to remove a mistaken dataset. Archive
keeps rows and schema metadata recoverable, hides the dataset from normal lists,
and disables public preview sharing. Use `get_archived_datasets` to find
archived dataset keys, then use `restore_dataset` to bring an archived dataset
back.

## Schema tools

Use schema tools when an existing active dataset needs columns changed without
recreating it:

```text
add_column
rename_column
drop_column
reorder_columns
update_dataset_metadata
update_dataset_project
```

Existing rows receive blank or default values when adding a column. Index columns
cannot be dropped, and generated index columns cannot be renamed.

Use `update_dataset_metadata` when the user wants agents to remember dataset
purpose, workflow rules, status conventions, or other JSON context without
changing rows.

Use `update_dataset_project` when the user asks to organize or move a dataset
between projects or into a project section. Pass `section_key` with
`project_key` to assign a section. Passing `null` for `project_key` leaves the
dataset ungrouped.

## Relationship tools

Use relationships when one dataset stores another dataset row's index value.

```text
list_dataset_relationships
create_dataset_relationship
resolve_dataset_relationship
delete_dataset_relationship
```

With enforcement enabled, row writes fail when a non-blank source value does not
match an existing target row.

For typed reference cells, use `{"type": "reference", "target": "dataset"}` to
store another Rowset dataset key or `{"type": "reference", "target": "project"}`
to store a Rowset project key. Rowset validates non-blank values in the same
account and stores canonical keys. When references are present, `get_dataset`
includes `dataset_references` and `project_references` grouped by source column
and target key.

## Image asset tools

Use image columns when a row needs a private visual asset.

```text
attach_image_to_dataset_row
get_dataset_image_asset
```

The hosted MCP server cannot read an agent's local file path. The agent must
read local image bytes itself and pass base64 or a data URI. Rowset writes an
opaque `asset:{key}` reference into the row cell.

`attach_image_to_dataset_row` accepts JPEG, PNG, or WebP bytes. Pass either
`row_id` or the dataset `index_value`, not both. Use `get_dataset_image_asset`
to retrieve asset metadata plus authenticated `content_url` and `thumbnail_url`
values. Rowset normalizes image bytes before storage, so asset `byte_size` and
`checksum` describe the stored Rowset file rather than the original file on disk.

## Audio asset tools

Use audio columns when a row needs a private audio file.

```text
attach_audio_to_dataset_row
get_dataset_audio_asset
```

The hosted MCP server cannot read an agent's local file path. The agent must
read local audio bytes itself and pass base64 or a data URI. Rowset writes an
opaque `asset:{key}` reference into the row cell.

`attach_audio_to_dataset_row` accepts MP3, WAV, M4A, AAC, Ogg, FLAC, or WebM
bytes. Pass either `row_id` or the dataset `index_value`, not both. Use
`get_dataset_audio_asset` to retrieve asset metadata plus authenticated
`content_url` values. Rowset stores audio bytes privately without transcoding.

## Public preview tools

Use public previews only when the user asks to share a read-only browser page:

```text
update_dataset_public_preview
```

Public previews are not an authentication mechanism for agents or applications.
Use authenticated MCP or REST for private row reads, writes, and exports. The
tool returns the public preview URL when sharing is enabled.

## Permissions

Agent API key permissions apply to MCP tools:

- **Read** keys can inspect account details, projects, datasets, rows, and exports.
- **Read + write** keys can create and update datasets, rows, projects,
  relationships, schema, and public preview settings.
- **Admin** keys can call `create_agent_api_key` to provision other agent API
  keys through REST or MCP.

Ask before destructive actions such as deleting rows, archiving datasets, or
clearing public preview passwords.
