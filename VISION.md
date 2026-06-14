# VISION.md

## Vision

Rowset should become the fastest trustworthy dataset backend for AI agents. It
should feel like a practical place for agents to create, mutate, export, and
share structured rows without making humans operate upload wizards or fragile
source-specific sync.

The durable product direction is: private by default, agent-native by design,
and honest about which operations are available through MCP and REST.

## What Should Not Drift

- The primary object is the dataset: headers, rows, semantic column metadata, and
  a stable index.
- The most important lookup path is by a user-meaningful key, not by UI scraping.
- MCP and REST are first-class interfaces, not afterthoughts.
- Public previews are for human review and lightweight sharing only.
- Agents should use MCP first, REST second, and browser automation last.
- Authenticated ownership boundaries matter more than convenience shortcuts.
- The UI should make agent setup and API outcomes visible quickly: MCP URL,
  REST base URL, dataset keys, row lookups, exports, and public preview URLs.

## Product Taste

Rowset should feel like a crisp developer/data utility:

- Fast to understand.
- Concrete about inputs and outputs.
- Calm and operational inside the app.
- Polished enough to trust with real business data.
- Technical without making users assemble every part themselves.

Avoid vague platform language. Prefer specific nouns like dataset, row, index
column, API key, MCP tool, public preview, CSV export, and Parquet export.

## Long-Term Direction

- Improve agent setup so users can connect trusted agents without copying secrets.
- Keep data mutation explicit, auditable, and easy to reason about.
- Expand schema and type handling when it improves API usefulness.
- Keep deployment and self-hosting approachable for small teams.

## Non-Goals

- Do not become a public spreadsheet host by default.
- Do not become a broad BI/dashboard product unless that directly improves
  dataset API workflows.
- Do not hide authentication or sharing tradeoffs behind convenience UI.
- Do not market source types, write-back modes, or agent capabilities before they
  are implemented and tested.
- Do not optimize for flashy UI at the cost of clear data inspection and safe
  programmatic access.

## Success Criteria

- A user can sign in, copy a setup prompt, and let a trusted agent create a
  usable API-backed dataset without custom backend code.
- A trusted AI agent can safely discover, read, create, update, and delete rows
  only within the authenticated user's datasets.
- API and MCP docs are accurate enough that users do not need to inspect source
  code to integrate.
- Private data remains private unless the user deliberately enables a sharing
  path.
- Future features strengthen the dataset/API bridge instead of diluting it.
