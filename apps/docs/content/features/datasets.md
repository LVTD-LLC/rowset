---
title: Working with datasets
description: Understand the FileBridge dataset lifecycle, index columns, public previews, and exports.
keywords: FileBridge datasets, CSV import, index columns, public preview
---

# Working with datasets

Datasets are the core object in FileBridge. A dataset starts as an uploaded file and becomes an API-addressable table after import.

## Dataset lifecycle

1. **Previewed** — FileBridge has read the file, detected headers, and shown sample rows.
2. **Processing** — You confirmed the import and FileBridge is building API rows.
3. **Ready** — Rows are imported and API endpoints are available.
4. **Failed** — Import stopped because the file could not be parsed or validated. The dataset page shows the parse error.

## Choosing an index column

Pick the column your apps and agents naturally use to find a row:

- `sku` for product catalogs
- `email` for people/contact lists
- `slug` for content inventories
- `external_id` for synced systems

If the file does not have a stable key, let FileBridge generate one.

## Public previews

Public previews are optional and separate from authenticated API access. Enable them from dataset settings when someone needs to view the data without an API client.

Use password protection when the link should not be casually forwarded.

## CSV exports

Use CSV export when a workflow needs a full snapshot instead of row-by-row API access. For automated systems, prefer the Dataset API unless the consumer explicitly expects CSV.
