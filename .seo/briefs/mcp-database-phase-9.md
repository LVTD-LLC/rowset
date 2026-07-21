# Phase 9 Research Brief: MCP Database

## Target

- URL: `/docs/database-mcp-server`
- Primary cluster: `mcp database`, `database mcp`
- Supporting terms: `database mcp server`, `mcp for database`, `SQL MCP server`
- Intent: definition plus architecture decision
- Measured opportunity: 480 US searches/month, KD 5, $14.12 CPC for the primary cluster
- SERP checked: 2026-07-21, Google US English desktop via DataForSEO live organic SERP

## Live SERP findings

The two primary queries return a mixed result set: the MCP introduction, official database MCP
products, open-source repositories, database-server directories, tutorials, and an AI Overview.
The most useful current primary/product results are:

1. Model Context Protocol introduction and authorization guidance.
2. Google MCP Toolbox for Databases.
3. Microsoft SQL MCP Server in Data API builder.
4. ExecuteAutomation's open-source multi-database MCP server.

People Also Ask questions include:

- What is database MCP?
- Can MCP connect to a database?
- Is there an MCP for SQL Server?
- Which databases support MCP?

The SERP explains how to connect agents to databases, but it rarely helps a user decide whether the
agent should touch a source-of-truth database at all. That architecture decision is the page's
information gain.

## Information-gain statement

Turn the generic “database MCP” query into a two-layer architecture decision:

- Use direct database MCP when the task depends on existing source-of-truth records, joins, and a
  mature database permission model.
- Use an agent-owned dataset layer when the workflow needs durable structured state, stable row
  identity, persistent instructions, and human review without production-database access.
- Use both when a constrained database tool reads source state and Rowset holds proposed or
  workflow-specific rows before a deterministic downstream write.

This is grounded in Rowset's real product boundary rather than a fabricated benchmark or generic
feature comparison.

## Entity and coverage map

- Model Context Protocol, server, client, tools, tool discovery
- SQL MCP server, database MCP server, PostgreSQL, MySQL, SQL Server, SQLite, NoSQL
- source of truth, workflow layer, configured entities, structured queries
- least privilege, RBAC, read-only role, authorization, audit logs, query limits, timeouts
- deterministic operations, NL2SQL risk, DML, schema exposure
- stable row identity, business key, `rowset_id`, dataset instructions
- private MCP and REST, scoped API keys, public read-only preview

## Verified claim ledger

| Claim | Primary source | Verification |
|---|---|---|
| MCP servers expose external capabilities as discoverable tools with defined inputs and behavior. | https://modelcontextprotocol.io/docs/getting-started/intro | Confirmed in official MCP documentation and independently reflected in Microsoft's SQL MCP overview. |
| Authorization is recommended for MCP servers handling databases, user-specific data, audited actions, or per-user rate limits. | https://modelcontextprotocol.io/docs/tutorials/security/authorization | Confirmed in the official MCP authorization guide. |
| Google MCP Toolbox connects agents to enterprise databases and supports generic database tools plus restricted structured custom tools. | https://github.com/googleapis/mcp-toolbox | Confirmed in the current official repository README. |
| Microsoft SQL MCP Server exposes configured entities through a role-aware abstraction and deterministic DML tools. | https://learn.microsoft.com/en-us/azure/data-api-builder/mcp/overview | Confirmed in Microsoft Learn, last updated 2026-05-15. |
| Microsoft's implementation intentionally avoids unrestricted NL2SQL and supports per-entity operations and field restrictions. | https://learn.microsoft.com/en-us/azure/data-api-builder/mcp/overview | Confirmed in Microsoft Learn's NL2SQL, schema, and RBAC sections. |
| Rowset uses stable index columns, scoped bearer API keys, private datasets, persistent instructions, and optional read-only previews. | `PRODUCT.md`, `TECH.md`, `apps/pages/content/docs/dataset-api.md` | Confirmed against current repository product and API documentation. |

## Draft requirements

- Put `MCP Database` at the start of the title and H1.
- Lead with a direct definition and decision rule.
- Add a balanced comparison table.
- State where direct database MCP is better without weakening Rowset's product boundary.
- Cover connection safety and stable row identity in dedicated sections.
- Answer the live PAA questions in visible FAQ content and `FAQPage` JSON-LD.
- Link the official MCP, Google, and Microsoft sources.
- Preserve the existing product CTA and relevant Rowset docs/use-case links.
- Add inbound links from MCP setup, Dataset API, and MCP-vs-REST content.

