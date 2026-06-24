---
title: MCP access
description: Connect AI agents to Rowset through the hosted MCP endpoint.
keywords: Rowset MCP, Streamable HTTP MCP, AI agents
---

# MCP access

Rowset includes a hosted MCP endpoint so compatible AI agents can discover and use datasets without browser automation.

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

Then discover datasets with:

```text
get_all_datasets
search_datasets
```

Discover or create project groups with:

```text
get_all_projects
search_projects
create_project
get_project
update_project
update_project_metadata
```

Use project metadata for source links, kickoff threads, planning docs, or other
JSON context that should stay with the project. Pass an empty object to
`update_project_metadata` to clear it.

To create a new ready dataset from an agent workflow, call:

```text
create_dataset
```

The tool returns the new dataset key. Pass `project_key` to create it inside an
existing project, or omit `project_key` to leave it ungrouped. Agents can use
that dataset key immediately with the row tools. Pass `description`,
`instructions`, or `metadata` when the dataset should carry persistent operating
context for future agent runs.

For a specific ready dataset, agents can use:

```text
get_dataset
list_dataset_rows
get_dataset_row
get_dataset_row_by_index
create_dataset_row
update_dataset_row
update_dataset_row_by_index
delete_dataset_row
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

Use `add_column`, `rename_column`, `drop_column`, and `reorder_columns` when an
existing ready dataset needs schema changes without recreating it. Existing rows
receive blank or default values when adding a column. Index columns cannot be dropped,
and generated index columns cannot be renamed.

Use `update_dataset_metadata` when the user wants agents to remember dataset
purpose, workflow rules, status conventions, or other JSON context without
changing rows.

Use `update_project` when the user asks to rename a project or change its
description. Passing an empty string for `description` clears it.

Use `archive_dataset` when the user asks to remove a mistaken dataset. Archive keeps
rows and schema metadata recoverable, hides the dataset from normal lists, and disables
public preview sharing. Use `restore_dataset` to bring an archived dataset back.

Use `update_dataset_project` when the user asks to organize or move a dataset
between projects. Passing `null` for `project_key` leaves the dataset ungrouped.

Use `update_dataset_public_preview` only when the user asks to share a read-only
browser preview. The tool returns the public preview URL.

Use MCP tools for agent workflows when available. If the runtime cannot configure
MCP, use the REST API only after the user approves REST API authentication.

## Agent setup prompt

The dashboard shows a ready-to-copy prompt for setting up an agent. The Agent access
docs show a masked example, the `npx skills add LVTD-LLC/rowset` install command,
and point users back to the dashboard copy button for the full prompt.
