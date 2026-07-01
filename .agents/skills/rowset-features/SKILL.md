---
name: rowset-features
description: Use when a user asks what Rowset can do, which MCP or REST features Rowset supports, how Rowset capabilities fit together, or whether a requested dataset workflow is supported.
---

# Rowset Features

Use this skill to explain Rowset's current feature surface accurately. Always
prefer live discovery over memory:

1. If MCP is connected, call `get_rowset_capabilities`.
2. Inspect live MCP tools and schemas before invoking named tools.
3. Use the generated API docs or `llms.txt` from the Rowset site for public
   reference material.

Do not claim Rowset-owned Google Sheets sync, dashboard upload wizards, or
spreadsheet write-back as active product capabilities.

## Core Capabilities

### MCP setup and verification

- Configure Rowset as a remote Streamable HTTP MCP server.
- Store the full API key in a private `ROWSET_API_KEY` environment variable.
- Verify auth with `get_user_info`.
- Load current feature guidance with `get_rowset_capabilities`.

### Datasets

- Discover datasets with `get_all_datasets` and `search_datasets`.
- Create ready API-backed datasets with `create_dataset`.
- Inspect one dataset with `get_dataset` before row work.
- Use `rowset_id` generation when no reliable business key exists.

### Dataset context and semantic schema

- Persist description, instructions, and JSON metadata with
  `update_dataset_metadata`.
- Persist semantic column metadata with `update_dataset_column_types`.
- Supported column types: `text`, `choice`, `integer`, `number`, `currency`,
  `boolean`, `date`, `datetime`, `email`, and `url`.
- Use column descriptions when an agent should not infer meaning from a header.

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
  read-only browser page.
- Public previews are not authentication and are not a replacement for MCP or
  REST access.

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
