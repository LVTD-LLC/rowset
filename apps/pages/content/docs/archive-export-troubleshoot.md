---
title: Archive, export, and troubleshoot
description: Recover archived datasets, export Rowset snapshots, and handle common MCP, REST, preview, and schema issues.
keywords: Rowset archive, restore dataset, export dataset, Rowset troubleshooting
---

# Archive, export, and troubleshoot

Use this page when a dataset is in the wrong state, a workflow needs a file
snapshot, or an agent cannot access the expected Rowset surface.

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

Use MCP row tools for live agent workflows. Use exports for handoff, audit, or
offline processing.

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
- Dataset not ready: wait for processing or use a ready API-created dataset.
- Row not found: check `row_id` or the configured index value.
- Column not found: call `get_dataset` and compare against current headers.
- Choice value rejected: use one of the configured choice labels.
- Reference value rejected: use a Rowset key or URL owned by the same account.

## Public preview issues

Public previews are read-only. If an agent or script needs data, use MCP or
REST. If a human cannot open the preview, check whether the preview is enabled,
password-protected, or disabled by archiving.
