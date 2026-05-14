---
title: Working with datasets
description: Understand the FileBridge dataset lifecycle, index columns, and exports.
keywords: FileBridge datasets, CSV import, index columns
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

## CSV exports

Use CSV export when a workflow needs a full snapshot instead of row-by-row API access. For automated systems, prefer the Dataset API unless the consumer explicitly expects CSV.

## Sharing

Use Public previews when a human needs a browser-friendly, read-only view. Use the authenticated Dataset API for applications and agents.
