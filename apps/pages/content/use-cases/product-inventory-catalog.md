---
title: Product or inventory catalog
description: Use Rowset for product or inventory catalogs with SKU rows, prices, supplier fields, links, exports, and read-only previews.
keywords: product catalog, inventory catalog, Rowset use case
---

# Product or inventory catalog

Use Rowset when a trusted agent needs to maintain product records, supplier
notes, links, prices, and snapshots without a custom catalog app.

## Starter shape

Create a `products` dataset indexed by `sku`.

| sku | name | status | price | supplier | product_url | notes |
| --- | --- | --- | --- | --- | --- | --- |
| SKU-1042 | Starter kit | active | 49 | Northstar | https://example.com/starter | Check bundle photo |
| SKU-1188 | Team kit | review | 129 | Acme | https://example.com/team | Price changed |
| SKU-1405 | Archive pack | archived | 24 | Studio Dev |  | Keep for old orders |

## Agent jobs

- Update structured product fields from trusted sources.
- Keep URLs, prices, supplier notes, and status in typed columns.
- Export CSV, JSONL, XLSX, SQLite, or Parquet snapshots.
- Share read-only catalog views with teammates.

## Workflow rules

Add instructions for price source of truth, archived products, and how agents
should handle missing supplier data. Mark URLs, prices, and status values with
semantic column metadata so downstream scripts do not have to guess.

## Connect it

Use [MCP access](/docs/connect-mcp/) for agent maintenance. Use
[public previews](/docs/share-public-previews/) only when humans need a
read-only catalog view.
