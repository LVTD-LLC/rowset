# Public product claim guidance

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
