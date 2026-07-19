---
name: rowset-features
description: Use when a user asks what Rowset can do through MCP, CLI, or REST, how current Rowset capabilities fit together, or whether a requested dataset workflow is supported.
---

# Rowset Features

Use this skill to explain Rowset's current feature surface accurately. Always
prefer live discovery over memory:

Do not load capabilities or list datasets merely because a session started.
Use the live discovery steps below when the user asks about Rowset's feature
surface or when troubleshooting requires current capability details.

1. Load the compact `available_topics` index through a bare
   `get_rowset_capabilities` call, `rowset capabilities` command, or REST
   capabilities request.
2. Request only relevant topics for detailed guidance. Use cases are opt-in;
   full mode retrieves the complete guide.
3. Inspect current MCP schemas, CLI help, or generated REST API docs for the
   interface the user selected.
4. Use `llms.txt` from the Rowset site to find current public reference material.

The sections below are orientation, not a complete or permanent feature list.
When they disagree with a live Rowset resource, follow the live resource.

Do not claim Rowset-owned Google Sheets sync, dashboard upload wizards, or
spreadsheet write-back as active product capabilities.

## Core Capabilities

### MCP setup and verification

- Configure Rowset as a remote Streamable HTTP MCP server.
- Store the full API key in a private `ROWSET_API_KEY` environment variable.
- Verify auth with `get_user_info` only for a new or failing connection. If
  Rowset is already configured and authenticated, skip connection verification
  and the activation handoff.
- Load the topic index with `get_rowset_capabilities`, then request specific
  `topics`. Set `include_use_cases` only when examples help, or `full` for the
  complete guide.

### Datasets

- When the relevant dataset is unknown, use `search_datasets` with a limit of 3;
  avoid listing unrelated datasets.
- Create ready API-backed datasets with `create_dataset`.
- Inspect one dataset with `get_dataset` before row work.
- Use `rowset_id` generation when no reliable business key exists.

### Dataset context and semantic schema

- Persist description, instructions, and JSON metadata with
  `update_dataset_metadata`.
- Persist semantic column metadata with `update_dataset_column_types`.
- Supported column types: `text`, `tags`, `choice`, `integer`, `number`, `currency`,
  `boolean`, `date`, `datetime`, `email`, and `url`.
- Use column descriptions when an agent should not infer meaning from a header.
- Use `tags` for comma-separated string values that should render as individual
  pills without changing row data returned through MCP or REST.

### Schema changes

- Add columns with `add_column`.
- Rename columns with `rename_column`.
- Drop non-index columns with `drop_column`.
- Reorder columns with `reorder_columns`.
- Relationship columns and target index columns must be unlinked before
  destructive schema changes.

### Relationships

Use dataset relationships when a source dataset column stores another dataset
row's index value. For example, `Messages.person_id` can point to
`People.person_id`.

- List relationships with `list_dataset_relationships`.
- Create relationships with `create_dataset_relationship`.
- Resolve a source row through a relationship with `resolve_dataset_relationship`.
- Delete relationship definitions with `delete_dataset_relationship`.
- With enforcement enabled, row writes fail when non-blank source values do not
  match an existing target row index.

### Projects

- Discover projects with `get_all_projects` and `search_projects`.
- Create projects with `create_project`.
- Inspect a project and its datasets with `get_project`.
- Discover project sections with `get_project_sections`.
- Create sections with `create_project_section`.
- Update project name or description with `update_project`.
- Replace project JSON metadata with `update_project_metadata`.
- Update sections with `update_project_section`.
- Archive sections with `archive_project_section`.
- Move datasets with `update_dataset_project`, optionally passing `section_key`
  with `project_key`.

Projects organize datasets and carry workflow metadata. Sections optionally
organize datasets inside one project. Neither changes authenticated access
boundaries.

### Rows

- List rows with search, filters, and sort through `list_dataset_rows`.
- Search rows across datasets with ranked hybrid retrieval through `search_rows`
  when vector search is enabled.
- Search rows within one known dataset through `search_dataset_rows`.
- Read rows with `get_dataset_row` or `get_dataset_row_by_index`.
- Create rows with `create_dataset_row`.
- Patch rows with `update_dataset_row` or `update_dataset_row_by_index`.
- Delete rows with `delete_dataset_row` only when the user requested deletion.

### Public previews

- Use `update_dataset_public_preview` only when the user asks to share a
  read-only dataset.
- Enabled public datasets have a browser preview and dedicated read-only JSON
  metadata and row endpoints.
- Unprotected public datasets need no credential. Password-protected public API
  requests require `X-Rowset-Public-Password` on every request.
- Public access is not a replacement for authenticated MCP or REST when data is
  private or any write is required.

### Archive, restore, and exports

- Archive datasets with `archive_dataset` without deleting rows or schema
  metadata.
- Restore archived datasets with `restore_dataset`.
- Use REST export endpoints for file snapshots:
  `/export.csv`, `/export.jsonl`, `/export.xlsx`, and `/export.sqlite`.

## Answering Capability Questions

When explaining Rowset, keep the answer grounded in one of these categories:

- MCP setup and auth
- Dataset discovery and creation
- Dataset context and semantic schema
- Schema changes
- Relationships
- Projects
- Rows
- Public previews
- Archive, restore, and export

If a user asks for a capability outside these categories, say it is not an
active Rowset product path unless the live MCP capability guide or API docs show
otherwise.
