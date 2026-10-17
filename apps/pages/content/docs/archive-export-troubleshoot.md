---
title: Archive, export, and troubleshoot
description: Recover archived datasets, export Rowset snapshots, and handle common MCP, REST, preview, and schema issues.
keywords: Rowset archive, restore dataset, export dataset, Rowset troubleshooting
---

# Archive, export, and troubleshoot

Use this page when a dataset is in the wrong state, a workflow needs a file
snapshot, or an agent cannot access the expected Rowset surface.

For normal dataset creation and row work, start with
[How Rowset datasets work](/docs/datasets) and
[Work with rows](/docs/work-with-rows). This page is for recovery, exports,
and operational checks.

## Archive instead of deleting

Archive mistaken or inactive datasets:

```text
archive_dataset
```

REST:

```http
DELETE {{ api_base_url }}/datasets/{dataset_key}
```

Archive keeps rows and schema metadata recoverable, hides the dataset from
normal lists, and disables public preview sharing.

## Restore a dataset

Find archived datasets:

```text
get_archived_datasets
```

Restore one:

```text
restore_dataset
```

REST:

```http
GET {{ api_base_url }}/datasets/archived
POST {{ api_base_url }}/datasets/{dataset_key}/restore
```

## Export a snapshot

Use exports when another tool expects a file:

```http
GET {{ api_base_url }}/datasets/{dataset_key}/export.csv
GET {{ api_base_url }}/datasets/{dataset_key}/export.jsonl
GET {{ api_base_url }}/datasets/{dataset_key}/export.xlsx
GET {{ api_base_url }}/datasets/{dataset_key}/export.sqlite
```

These private REST exports require a bearer API key; a **Read** key is enough.
You do not need to enable a public preview. See [API authentication and key
permissions](/docs/api-overview#authentication) before sharing agent access.

### Choose a format

| Format | Use it for | What the file contains |
| --- | --- | --- |
| CSV | Spreadsheet imports and simple tabular handoffs | A header row followed by data rows |
| JSONL | Line-by-line processing in scripts | One JSON object per line, keyed by column name |
| XLSX | A spreadsheet workbook | A `Rows` sheet with headers and data |
| SQLite | Local SQL queries | A `rows` table with text columns |

Values in these exports are serialized as text; an empty value becomes an empty
string. JSONL is not the row-list API response: it does not wrap each record in
`id`, `index_value`, or `data` fields. Keep your dataset's index column in the
handoff if the next step needs to identify records.

### Save a private snapshot

Set `ROWSET_API_KEY` privately in your runtime and `DATASET_KEY` to the dataset
you intend to export. This example saves JSONL without making the dataset public:

```bash
umask 077
curl --fail --silent --show-error \
  --header "Authorization: Bearer ${ROWSET_API_KEY:?Set ROWSET_API_KEY privately}" \
  --output snapshot.jsonl \
  "{{ api_base_url }}/datasets/${DATASET_KEY:?Set DATASET_KEY}/export.jsonl"
```

Check the command's exit status before using the file. Treat the downloaded
snapshot as private data, too.

### Know the export boundary

A REST export reads the **whole dataset**, in row-number order. Row-list search,
filters, sorting, `limit`, and `offset` do not narrow the export. If you need only
selected records, use the [paginated row-list API](/docs/dataset-api#list-rows)
and write the returned `data` objects to a separate file in your own script.

The file is a tabular handoff, not a complete Rowset backup. It does not package
dataset instructions, semantic column configuration, relationships, or attached
asset files. Save needed context separately with
[dataset inspection](/docs/dataset-api#inspect-a-dataset). For a handoff that must
match a fixed state, pause writes while exporting; do not assume a request made
during concurrent edits is an atomic point-in-time backup.

Use MCP row tools for live agent workflows. Use exports for handoff, audit, or
offline processing. This REST export contract was checked on **October 17, 2026**;
see the [generated API reference]({{ api_docs_url }}) for the current endpoints.

## Common MCP issues

Missing authorization usually means the MCP request is not sending:

```http
Authorization: Bearer {{ api_key_placeholder }}
```

For Codex/OpenClaw-compatible clients, configure the server with:

```bash
codex mcp add rowset --url {{ mcp_url }} --bearer-token-env-var ROWSET_API_KEY
```

Then make sure the agent runtime can read the full `ROWSET_API_KEY`.

If a tool argument fails validation, ask the agent to call
`get_rowset_capabilities` and use live MCP tool discovery before retrying.

## Common dataset issues

- Dataset not found: check that the key belongs to the authenticated Rowset account.
- Dataset archived: restore the dataset before making row or schema changes.
- Row not found: check `row_id` or the configured index value.
- Column not found: call `get_dataset` and compare against current headers.
- Choice value rejected: use one of the configured choice labels.
- Reference value rejected: use a Rowset key or URL owned by the same account.

## Public preview issues

Public previews are read-only. If an agent or script needs data, use MCP or
REST. If a human cannot open the preview, check whether the preview is enabled,
password-protected, or disabled by archiving.
