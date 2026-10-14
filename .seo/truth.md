# Public product claim guidance

## API-key access boundary — checked 2026-10-12

Rowset API keys select account-wide Read, Read + write, or Admin capability
levels, not per-dataset grants. Read + write permits destructive operations,
including row deletion and dataset archiving. Dataset instructions are workflow
guidance, not an authorization boundary. Sources: `apps/core/services.py`
(`agent_api_key_access_level_allows`), `apps/api/auth.py`, and
`apps/pages/content/docs/connect-mcp.md` section 7, checked on main c68535a.
Avoid describing Rowset access as "scoped dataset access." When discussing
scoped keys, name the actual account-wide permission level.

Reviewed 2026-09-16 at base c48ec63. Recheck after changes to billing, auth, exports or integrations.

| Claim | Source | Verified |
|---|---|---|
| Trial duration is seven days | rowset/settings.py TRIAL_DURATION_DAYS | 2026-09-16 |
| Hosted MCP/private REST require bearer API-key auth | apps/api/auth.py; apps/mcp_server/auth.py; TECH.md | 2026-09-16 |
| Enabled public previews provide read-only access, optional password protection | apps/datasets/public_previews.py; apps/pages/content/docs/dataset-api.md | 2026-09-16 |
| Snapshot formats are CSV, JSONL, XLSX, SQLite, Parquet | apps/datasets/services.py; apps/api/views.py; TECH.md | 2026-09-16 |
| Agents own upstream source access; Rowset does not provide source sync connectors | PRODUCT.md, existing brand guardrails | 2026-09-16 |

## Comparison claims rechecked 2026-09-18

| Claim | Source | Verified |
|---|---|---|
| Rowset supports hosted and self-hosted deployments; do not describe it as hosted-only or deny the existing open-source product positioning | SELF_HOSTING.md; apps/pages/content/docs/self-hosting.md; .seo/brand.md; public source repository | 2026-09-18 |
| Baserow provides a built-in MCP server for workspace CRUD as well as its REST API; compare workflow scope, not an alleged lack of MCP | https://baserow.io/user-docs/mcp-server; https://baserow.io/blog/baserow-mcp-server-ai-integration | 2026-09-18 |

## Google Sheets comparison verification — 2026-09-19

| Claim | Source | Read date / risk |
|---|---|---|
| Google's official Sheets MCP server remains in Developer Preview; do not describe it as absent or generally available | https://developers.google.com/workspace/sheets/api/reference/mcp; https://developers.google.com/workspace/preview | 2026-09-19 / high, competitor availability |
| Default Sheets API read and write quotas are each 300/minute/project and 60/minute/user/project; standard use has no additional cost, with later-2026 over-quota billing still described as planned | https://developers.google.com/workspace/sheets/api/limits | 2026-09-19 / high, quotas and pricing |
| Sheets documents 10 million cells or 18,278 columns; the 20-million-cell announcement is an opt-in beta, not the universal standard limit | https://support.google.com/drive/answer/37603; https://workspaceupdates.googleblog.com/2026/04/faster-performance-and-doubled-cell-limits-in-Google-Sheets.html | 2026-09-19 / high, capacity |
| Gemini access and usage depend on eligibility and plan; past promotional allowances are not a current capacity promise | https://support.google.com/docs/answer/14356410; https://support.google.com/a/users/answer/16848293 | 2026-09-19 / high, availability |

These sources still support the comparison's core distinctions. This was a
verification and source-maintenance pass, not a finding that Google's MCP,
quota, or capacity claims were false. Recheck before changing those claims or
after a provider announcement; do not infer an account-specific entitlement.

## High-risk product claims

Do not promise private access without authentication, automatic source synchronization, or security/compliance certifications without specific current evidence. Hosted Pro price remains the existing approved brand value; Stripe catalog was not queried in this run.

## Airtable MCP capability — checked 2026-09-24

Airtable provides an official MCP server for external agents; record reads and
writes follow existing Airtable permissions. Do not frame external MCP access
as exclusive to Rowset. Source: https://support.airtable.com/articles/9897799762-using-the-airtable-mcp-server.
Scope: MCP capability, not a re-verification of July pricing or every API quota.

## NocoDB comparison — checked 2026-10-14

NocoDB supports MCP record reads and writes on all editions, with broader
workspace tools on Cloud and licensed self-hosted editions. Do not treat an
agent doing most writes as evidence that Rowset is superior. Source:
https://nocodb.com/docs/apis-and-mcp/mcp (read 2026-10-14).
Rowset account-wide permission levels remain as documented above; previews
do not enforce approval before writes. Sources: docs/connect-mcp.md and
docs/mcp-rest-public-previews.md at main 221201f. No comparative scale benchmark
or NocoDB runtime test was performed.
