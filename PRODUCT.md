# PRODUCT.md

## Product

Rowset gives AI agents a stable backend for user-owned structured datasets.
Instead of asking humans to manage upload wizards or fragile third-party sync,
trusted agents create, inspect, update, export, and share datasets through MCP or
REST.

Rowset is open source and self-hostable. People can use the hosted product for
the fastest setup or run the same code on infrastructure they control.

The core promise is simple: sign in, copy the agent setup prompt, give a trusted
agent an API key as a bearer token, and let it manage API-backed datasets with
clear ownership boundaries.

## Audience

- People who delegate data work to AI agents: founders, operators, analysts,
  engineers, and internal-tool builders.
- Developers who need a quick programmatic dataset backend for agent workflows.
- AI-agent users who need agents to read and update structured user data through
  MCP or REST instead of scraping web pages.
- Small teams that need lightweight sharing, exports, and programmatic access
  before investing in a full internal data platform.

## Primary Jobs

- Copy a Rowset setup prompt into a trusted AI agent.
- Let the agent authenticate through hosted MCP or REST with a bearer API key.
- Let agents create datasets with headers, rows, and a stable index.
- Let agents discover datasets, inspect schemas, and perform row operations
  through authenticated MCP or REST.
- Share enabled datasets through a read-only browser preview or public JSON API.
- Export CSV, JSONL, XLSX, SQLite, or Parquet snapshots when a consumer needs a
  file rather than row access.
- Manage public preview settings through API and MCP.

## Core Workflows

1. A user signs in and copies the Rowset setup prompt.
2. The agent reads `SKILL.md` and configures hosted MCP with a bearer API key.
3. The agent creates or discovers datasets through MCP or REST.
4. The agent performs row CRUD, exports snapshots, or enables a public preview
   when the user asks.
5. The UI remains a control surface for setup, settings, recent dataset state,
   exports, and public preview review.

Agents can read local files, Google Sheets, databases, or other sources using
their own capabilities, then send structured dataset data to Rowset through
MCP or REST. Rowset does not own those upstream integrations.

## Brand Personality

Direct, technical, and calm. Rowset should feel like a practical agent
utility, not a spreadsheet replacement or a no-code upload wizard. The voice is
specific about what agents can do and honest about when users need an account or
API key. Open source and self-hosting are core identity traits, not details left
for the footer or deployment documentation.

## In Scope

- Authenticated REST API for users, datasets, rows, exports, and public preview
  settings.
- Hosted MCP tools with bearer API-key auth.
- Agent-created datasets, row storage, schema metadata, and row CRUD.
- Public read-only dataset previews and JSON reads with optional password protection.
- User-facing docs for setup, datasets, API access, MCP access, and agent access.
- A small human UI for agent handoff, settings, recent datasets, exports, and
  preview review.
- Deployment through Docker Compose, Render, and CapRover-oriented files.

## Out Of Scope

- Rowset-owned source connectors, sync, or write-back.
- Public dataset access as a replacement for private reads or authenticated write access.
- Browser automation as the preferred agent integration path.
- A general-purpose BI dashboard, warehouse, or ETL orchestration suite.
- Client-side exposure of API keys or other secrets.
- Unsupported file types or sync providers described as available before code,
  tests, and docs exist.

## Design Principles

- Lead with the agent handoff: the first useful action is copying the setup
  prompt into an AI agent.
- Keep humans out of row operations: dataset creation, updates, public preview
  settings, and row CRUD should be available through MCP and REST.
- Expose machine-readable truth: show API base URLs, MCP URLs, dataset keys, and
  public preview URLs clearly.
- Treat the UI as a control surface: settings, verification, recent state, and
  recovery belong in the product UI; bulk data operations belong to agents.
- Remove fragile integrations from the core promise: agents can connect to
  Google Sheets or read local files themselves, Rowset does not own that
  dependency.

## What Good Looks Like

- A new user can sign in, copy the prompt, and connect an agent in minutes.
- An AI agent can verify a new setup with `get_user_info`, find an unknown
  dataset with `search_datasets(limit=3)`, inspect it with `get_dataset`, create
  datasets with `create_dataset`, and operate on rows without browser
  automation or eager startup discovery.
- Dataset APIs are predictable: stable keys, bounded pagination, clear errors,
  and ownership enforcement.
- Sensitive data stays private by default.
- Docs and UI make the right path obvious: deliberate public reads for shared data,
  authenticated REST/MCP for private reads and all writes.
- Changes to dataset behavior remain covered by focused tests.

## Accessibility & Inclusion

Use WCAG AA contrast for text and controls. Preserve keyboard access and visible
focus for all dashboard actions. Avoid motion that delays task completion, and
respect reduced-motion preferences. Copy must be readable by non-engineers while
still being precise enough for agents and developers.
