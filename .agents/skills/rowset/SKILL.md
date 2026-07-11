---
name: rowset
description: Use when a user asks to connect an AI agent to Rowset, configure Rowset MCP or REST access, or manage Rowset datasets. Covers bearer API key setup, hosted MCP discovery, capability discovery, dataset/project creation and lookup, row CRUD, relationships, semantic schema, REST file export fallback, public preview sharing, and privacy/destructive-action guardrails.
---

# Rowset

## Overview

Use Rowset as a stable backend for user-owned structured datasets. Prefer the
hosted MCP server for agent workflows, use the REST API only when MCP cannot be
configured, and keep browser automation as a last resort.

Companion skills in this repo:

- `rowset-features` explains the current Rowset feature surface.
- `rowset-use-cases` gives concrete dataset patterns for common workflows.

Use live MCP discovery, `get_rowset_capabilities`, and `llms.txt` as the current
source of truth. Static skill text is a startup guide, not a replacement for the
connected server's current tool schemas.

## Required Prompt Inputs

Expect the user or setup prompt to provide:

- `Rowset MCP URL`
- `Rowset REST API base`
- `Rowset API key`
- A Rowset skill URL or install command

If any required connection value is missing, ask for it before attempting
authenticated Rowset work. Never ask the user to paste a key into public chat or
save it in a tracked file.

## Setup Workflow

1. Read the full setup prompt before acting and identify the `Rowset MCP URL`,
   `Rowset REST API base`, and full `Rowset API key`.
2. Store the full API key in a private environment variable named
   `ROWSET_API_KEY` or in the client's secret store. Do not print it in logs,
   screenshots, public chats, generated files, or final responses. Do not
   commit it, paste it back to chat, or save it in a tracked config file.
3. Configure a remote Streamable HTTP MCP server named `rowset` with the
   provided MCP URL.
4. Configure the MCP client's bearer-token environment variable to
   `ROWSET_API_KEY` so requests send `Authorization: Bearer <key>`.
5. For Codex/OpenClaw-compatible clients, use this command shape:

   ```bash
   codex mcp add rowset --url <Rowset MCP URL> --bearer-token-env-var ROWSET_API_KEY
   ```

   Replace `<Rowset MCP URL>` with the exact URL from the setup prompt. Do not
   put the raw key in the command.
6. If the client only supports custom headers, set `Authorization` to
   `Bearer <key>`. Use `X-API-Key` only for REST clients that cannot send bearer
   tokens.
7. Discover available MCP tools and their schemas from the connected server
   before invoking named tools. Treat the live MCP server and REST API docs as
   the source of truth for exact inputs.
8. After connecting, call `get_user_info` to verify authentication.
9. Call `get_rowset_capabilities` to load the current feature and workflow
   guide into context.
10. Call `get_all_datasets` or `search_datasets` to verify dataset discovery
    works. If auth fails, confirm `ROWSET_API_KEY` contains the full key, not only the visible prefix.

## Dataset Workflow

Use this default order when the user asks Rowset to work with data:

1. Call `get_all_datasets` to discover datasets available to the authenticated
   profile. It returns paginated metadata, not row contents.
2. Call `get_dataset` before row operations on a specific dataset so you know the
   headers, key, index column, semantic column types, persistent instructions,
   JSON metadata, relationships, readiness, and public preview state.
3. Create datasets with `create_dataset` when the user asks for a new structured
   backend. Provide `headers`, `rows`, or both. If there is no reliable business
   key, omit `index_column` and let Rowset generate `rowset_id`.
4. Manage semantic column metadata with `update_dataset_column_types` when the
   user asks to improve schema types. Supported types include `text`, `tags`, `integer`,
   `number`, `currency`, `boolean`, `date`, `datetime`, `email`, and `url`.
   Tags columns store comma-separated strings while the Rowset UI renders each
   non-blank segment as a pill. Choice columns accept fixed string values and
   can carry column descriptions.
5. Use `get_all_projects`, `create_project`, `get_project`, and
   `update_dataset_project` when the user wants to organize datasets into
   project groups.
6. Use row tools for dataset contents:
   `search_rows` for ranked search across datasets; `list_dataset_rows`,
   `search_dataset_rows`, `get_dataset_row`,
   `get_dataset_row_by_index`, `create_dataset_row`, `update_dataset_row`,
   `update_dataset_row_by_index`, and `delete_dataset_row`.
7. Use relationship tools when one dataset stores another dataset row's index
   value: `list_dataset_relationships`, `create_dataset_relationship`,
   `resolve_dataset_relationship`, and `delete_dataset_relationship`.
8. Use schema mutation tools for existing ready datasets:
   `add_column`, `rename_column`, `drop_column`, and `reorder_columns`.
9. Use REST only after the user approves REST fallback or when MCP cannot perform
   the requested action. For file exports, use the current API docs and the REST
   paths under the provided REST API base:
   `GET /datasets/{dataset_key}/export.csv`,
   `GET /datasets/{dataset_key}/export.jsonl`,
   `GET /datasets/{dataset_key}/export.xlsx`, or
   `GET /datasets/{dataset_key}/export.sqlite`.

## Public Preview Workflow

Use `update_dataset_public_preview` only when the user asks to share a dataset
through a read-only browser page. Public previews are not authentication and are
not a substitute for private MCP or REST access.

When changing preview settings:

- Confirm whether preview access should be enabled or disabled.
- Ask whether a password is required when the request is ambiguous.
- Keep page size bounded to the server-supported schema.
- Return the public preview URL when the tool provides it.

## Safety Rules

- Prefer MCP tools over browser automation.
- Keep private authenticated dataset access as the default.
- Keep user data private and only access the Rowset resources needed for the
  task.
- Ask before destructive data actions such as deleting rows or datasets, clearing
  preview passwords, disabling previews someone may depend on, or replacing
  meaningful data.
- Do not expose API keys, OAuth tokens, raw secrets, private dataset contents, or
  row data in logs, screenshots, public pages, commits, or final messages.
- Do not describe public previews as secure private access.
- Do not claim Rowset-owned Google Sheets sync, dashboard upload wizards, or
  spreadsheet write-back flows are active product capabilities.

## Discovery Fallbacks

If the MCP client can browse public URLs, read the Rowset `llms.txt` page from
the same site as the setup prompt. It summarizes current capabilities, skills,
REST fallback paths, use-case guides, and privacy guardrails.

If MCP is connected, prefer `get_rowset_capabilities` over static docs because
it comes from the live Rowset server.

## If MCP Is Unavailable

1. Explain that MCP is the preferred Rowset path.
2. Ask the user before using REST API authentication.
3. Store the API key privately and send it as `Authorization: Bearer <key>`.
4. Inspect the current REST API docs from the provided REST API base before
   making dataset or row requests.
5. Keep the same ownership, privacy, and destructive-action rules as the MCP
   workflow.
