---
title: MCP access
description: Connect AI agents to Rowset through the hosted MCP endpoint.
keywords: Rowset MCP, Streamable HTTP MCP, AI agents
---

# MCP access

Rowset includes a hosted MCP endpoint so compatible AI agents can discover and use datasets without browser automation.

If you are deciding what kind of data should sit behind an agent, start with
[What is an agent-managed dataset?](/blog/agent-managed-datasets). It explains
where MCP fits alongside row identity, schema, dataset instructions, and human
review.

Use Rowset's hosted MCP server when the agent needs a private, user-owned
dataset backend but you do not want to expose a production database directly.
Direct database MCP servers are better when the agent must query an existing
Postgres/MySQL/SQLite system and the operator is ready to manage database
credentials, permissions, query cost, and schema safety. Rowset is the narrower
choice for agent-owned task boards, CRMs, feedback queues, catalogs, QA trackers,
and other structured row workflows that should stay behind a scoped Rowset API
key.

## MCP URL

```text
{{ mcp_url }}
```

## Authentication

Add the MCP URL to a compatible remote MCP client, then configure the agent API
key as the bearer token for that server.

The dashboard setup prompt includes your API key. The visible preview masks it,
but the copied prompt includes the real key.

Store the key in a private environment variable such as `ROWSET_API_KEY` or in
your client's secret store. If your client has a "bearer token env var" setting,
set it to `ROWSET_API_KEY` so MCP requests include:

```http
Authorization: Bearer {{ api_key_placeholder }}
```

For Codex/OpenClaw-compatible clients, use:

```bash
codex mcp add rowset --url {{ mcp_url }} --bearer-token-env-var ROWSET_API_KEY
```

Make sure `ROWSET_API_KEY` is present in the agent runtime environment and holds
the full key, not only the visible key prefix.

If your client only supports custom headers, set a custom `Authorization` header
with the value `Bearer {{ api_key_placeholder }}`. Use `X-API-Key` only for REST
clients that cannot send bearer tokens.

## First checks

Do not treat this page as the source of truth for tool names or inputs. The MCP
server and the REST API docs describe the current surface.

After connecting, discover the available tools and schemas from your MCP client,
then verify the authenticated user/profile with the user-info tool exposed by the
current MCP server.

Then load the current Rowset feature guide:

```text
get_rowset_capabilities
```

The guide summarizes feature groups, recommended startup order, REST fallback
paths, use-case patterns, and privacy guardrails. Use MCP tool discovery for the
exact current input schemas.

When the agent is setting up a new workflow, have it read the relevant use case
first, then call `create_dataset` with a clear `description`, `instructions`,
and stable `index_column`. Useful starting points include the
[agent-managed personal CRM](/use-cases/personal-crm), [agent task
board](/use-cases/agent-task-board), and [feedback triage
workflow](/use-cases/feedback-triage).

Agent API key permissions apply to MCP tools. Read keys can inspect data, Read +
write keys can mutate datasets and projects, and Admin keys can also call
`create_agent_api_key` to provision another key.

Then discover datasets with:

```text
get_all_datasets
get_archived_datasets
search_datasets
```

Discover or create project groups with:

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

Use project metadata for source links, kickoff threads, planning docs, or other
JSON context that should stay with the project. Use sections for optional
grouping inside a project, such as Blog or Sales. Pass an empty object to
`update_project_metadata` to clear it.
Use `archive_project` when a project should disappear from normal project
discovery. Archiving a project does not delete or archive its datasets.

To create a new ready dataset from an agent workflow, call:

```text
create_dataset
```

The tool returns the new dataset key. Pass `project_key` to create it inside an
existing project, or pass both `project_key` and `section_key` to create it
inside a project section. Omit both fields to leave it ungrouped. Agents can use
that dataset key immediately with the row tools. Pass `description`,
`instructions`, or `metadata` when the dataset should carry persistent operating
context for future agent runs.

For row discovery across datasets, agents can use:

```text
search_rows
```

For a specific ready dataset, agents can use:

```text
get_dataset
list_dataset_rows
search_dataset_rows
get_dataset_row
get_dataset_row_by_index
create_dataset_row
attach_image_to_dataset_row
get_dataset_image_asset
update_dataset_row
update_dataset_row_by_index
delete_dataset_row
list_dataset_relationships
create_dataset_relationship
resolve_dataset_relationship
delete_dataset_relationship
add_column
rename_column
drop_column
reorder_columns
update_dataset_metadata
update_dataset_project
update_dataset_public_preview
archive_dataset
restore_dataset
```

Dataset and row tools enforce the authenticated user's ownership boundary.
`create_dataset`, row mutation tools, and schema mutation tools change dataset
contents, so agents should ask the user before using them unless the user explicitly
requested the change.

Use `search_rows` when vector search is enabled and the agent needs ranked row
matches across datasets. It accepts natural-language search text, dataset or
project filters, row field filters, archived filtering, sort, and limit. Use
`search_dataset_rows` when the agent already knows the dataset key and wants the
same ranked search inside that one dataset. Results are hydrated from Rowset
rows and include match metadata such as source, ranks, scores, point id, chunk
index, and content hash. Rowset/Postgres remains the source of truth.

Use `add_column`, `rename_column`, `drop_column`, and `reorder_columns` when an
existing ready dataset needs schema changes without recreating it. Existing rows
receive blank or default values when adding a column. Index columns cannot be dropped,
and generated index columns cannot be renamed.

Use `update_dataset_metadata` when the user wants agents to remember dataset
purpose, workflow rules, status conventions, or other JSON context without
changing rows.

Use `attach_image_to_dataset_row` for image columns after the target row exists.
The tool accepts JPEG, PNG, or WebP bytes encoded as base64 or a data URI. For
local files, agents should read the file bytes and encode them before calling
the hosted MCP tool; hosted MCP cannot read the agent's local file path.

Pass either `row_id` or the dataset `index_value`, not both. Rowset writes an
opaque `asset:{key}` reference into the row cell. Use `get_dataset_image_asset`
to retrieve asset metadata plus authenticated `content_url` and `thumbnail_url`
values. Rowset normalizes image bytes before storage, so asset `byte_size` and
`checksum` describe the stored Rowset file rather than the original file on disk.

`get_dataset` returns dataset context, semantic column schema, and relationship
summaries for the dataset being inspected. Agents should call it before row
operations so they do not miss instructions, choice values, or links to related
datasets.

For typed reference cells, use `{"type": "reference", "target": "dataset"}` to
store another Rowset dataset key or `{"type": "reference", "target": "project"}`
to store a Rowset project key. Rowset validates non-blank values in the same
account and stores canonical keys. When references are present, `get_dataset`
includes `dataset_references` and `project_references` grouped by source column
and target key.

Use dataset relationship tools when a source dataset column stores another
dataset row's index value. For example, a Personal CRM messages dataset can store
`person_id` values that point at the People dataset's `person_id` index. With
enforcement enabled, row writes fail when a non-blank source value does not match
an existing target row.

Use `update_project` when the user asks to rename a project or change its
description. Passing an empty string for `description` clears it.

Use `archive_dataset` when the user asks to remove a mistaken dataset. Archive keeps
rows and schema metadata recoverable, hides the dataset from normal lists, and disables
public preview sharing. Use `get_archived_datasets` to find archived dataset keys, then
use `restore_dataset` to bring an archived dataset back.

Use `update_dataset_project` when the user asks to organize or move a dataset
between projects or into a project section. Pass `section_key` with `project_key`
to assign a section. Passing `null` for `project_key` leaves the dataset
ungrouped.

Use `update_dataset_public_preview` only when the user asks to share a read-only
browser preview. The tool returns the public preview URL.

Use MCP tools for agent workflows when available. If the runtime cannot configure
MCP, use the REST API only after the user approves REST API authentication.

## Public agent-readable overview

Agents that can read public URLs can use:

```text
{{ llms_txt_url }}
```

This generated page summarizes current Rowset capabilities, skill URLs, REST
fallback paths, use-case patterns, and guardrails. It never includes private API
keys or dataset contents.

## Agent setup prompt

The dashboard shows a ready-to-copy prompt for setting up an agent. The Agent access
docs show a masked example, the `npx skills add LVTD-LLC/rowset` install command,
and point users back to the dashboard copy button for the full prompt.
