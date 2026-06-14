# PRODUCT.md

## Product

FileBridge helps builders, operators, and AI-agent-heavy teams turn messy
spreadsheet-like data into stable, private, programmatic interfaces without
building a custom backend for each file.

The core promise is simple: upload or connect tabular data, inspect it, choose a
lookup key, and get a reliable dataset API plus MCP tools that agents can use
without browser automation.

## Audience

- Developers who need a quick API over CSV, Parquet, or spreadsheet data.
- Operators who maintain product catalogs, contact lists, content inventories,
  or operational tables in files or Google Sheets.
- AI-agent users who need agents to read and update structured user data through
  MCP or REST instead of scraping web pages.
- Small teams that need lightweight sharing, exports, and programmatic access
  before investing in a full internal data platform.

## Primary Jobs

- Preview a tabular source before committing it to the app.
- Select a stable index column such as `sku`, `email`, `slug`, or `external_id`.
- Generate a `filebridge_id` index when the source lacks a reliable key.
- Turn confirmed data into row-level REST endpoints and MCP tools.
- Let agents discover datasets, inspect schemas, and perform row operations
  through authenticated MCP.
- Share read-only public previews with humans when a browser page is enough.
- Export full CSV snapshots when a consumer needs a file rather than row access.
- Optionally sync supported Google Sheets-backed changes when explicit Sheets
  access is configured.

## Core Workflows

1. A user uploads a CSV or Parquet file, or enters a Google Sheets URL.
2. FileBridge parses headers, infers semantic column types, and shows sample rows.
3. The user chooses an index column or lets FileBridge generate one.
4. FileBridge imports rows and marks the dataset ready.
5. The user consumes the dataset through REST, hosted MCP, CSV export, or a
   read-only public preview.

For agent setup, FileBridge gives users a copy/paste prompt with the hosted MCP
URL, REST API base URL, and `SKILL.md` instructions URL. The normal MCP path uses
browser-based OAuth rather than pasted API keys.

## In Scope

- Dataset preview, import, validation, row storage, and row CRUD.
- CSV and Parquet uploads.
- Public Google Sheets imports.
- Private Google Sheets import and write-back when explicit OAuth or service
  account credentials are configured.
- Authenticated REST API for users and datasets.
- Hosted MCP tools with OAuth and API-key compatibility fallback.
- Public read-only dataset previews with optional password protection.
- User-facing docs for setup, datasets, API access, MCP access, and agent access.
- Deployment through Docker Compose, Render, and CapRover-oriented files.

## Out Of Scope

- Public previews as a replacement for private API or MCP authentication.
- Browser automation as the preferred agent integration path.
- A general-purpose BI dashboard, warehouse, or ETL orchestration suite.
- Large-file processing beyond current upload and memory limits.
- Client-side exposure of API keys or OAuth tokens.
- Unsupported file types or sync providers described as available before code,
  tests, and docs exist.

## What Good Looks Like

- A new user can create a ready dataset and use its API in minutes.
- An AI agent can verify setup with `get_user_info`, discover datasets with
  `get_all_datasets`, and operate on rows without browser automation.
- Dataset APIs are predictable: stable keys, bounded pagination, clear errors,
  and ownership enforcement.
- Sensitive data stays private by default.
- Docs and UI make the right path obvious: public preview for humans, REST/MCP
  for systems and agents.
- Changes to dataset behavior remain covered by focused tests.
