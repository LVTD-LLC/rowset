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

## High-risk claims

Do not promise private access without authentication, automatic source synchronization, or security/compliance certifications without specific current evidence. Hosted Pro price remains the existing approved brand value; Stripe catalog was not queried in this run.
