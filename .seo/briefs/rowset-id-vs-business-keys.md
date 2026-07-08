# SEO Brief: Rowset rowset_id vs business keys

## Selection

- Date: 2026-07-08
- Selected candidate: Rowset `rowset_id` vs business keys
- Type: comparison / decision guide
- Slug: `/blog/rowset-id-vs-business-keys`
- Target keyword: `Rowset rowset_id`, plus adjacent intent for `business key`, `surrogate key`, `dataset index column`, and agent row identity.
- Why selected: It is the highest-priority unshipped candidate in `.seo/content-ledger.md` after earlier candidates were already shipped. It is product-native, supports Rowset's Dataset API/MCP surface, and fills a gap opened by the index-column guide.

## Product-Led SEO Check

- User job: decide how a trusted agent should identify rows before creating or updating a Rowset dataset.
- Product surface: Dataset API, MCP tools, dataset instructions, schema design, relationships, exports/imports.
- Business job: reduce unsafe agent writes, support API/MCP activation, and internally link deeper dataset docs from existing blog/use-case pages.
- Moat: Rowset-specific generated index semantics, by-index operations, dataset instructions, and relationship behavior are not generic keyword-list content.

## AI SEO Check

- Direct answer in opening: yes.
- Extractable claims: direct short rule, decision table, safe migration pattern, instruction templates, FAQ.
- Freshness/date signals: post dated 2026-07-08; external docs cited with current URLs and dates where available.
- Entity coverage: Rowset, `rowset_id`, business key, index column, MCP tools, Dataset API, relationships, idempotency, generated identity, PostgreSQL, Stripe.
- Schema consideration: Rowset blog renderer provides BlogPosting/metadata; article includes FAQ section for extractability.

## Claim Ledger

| Claim | Source(s) | Status |
|---|---|---|
| Rowset generates `rowset_id` when `index_column` is omitted during dataset creation. | `apps/pages/content/docs/dataset-api.md`; `apps/datasets/services.py` (`GENERATED_INDEX_BASENAME`) | verified by product source |
| Rowset by-index REST/MCP paths read and patch rows by the dataset index value. | `apps/pages/content/docs/dataset-api.md`; `apps/pages/content/docs/work-with-rows.md`; `apps/mcp_server/server.py` | verified by product source |
| Generated index columns cannot be renamed, and index columns cannot be dropped. | `apps/pages/content/docs/dataset-api.md`; `apps/pages/content/docs/design-schema.md`; `apps/pages/content/docs/mcp-tools.md` | verified by product source |
| Rowset accepts unchanged generated index values in full-row updates but should reject rewriting generated values as custom identity. | `apps/datasets/tests/test_csv_datasets.py` generated-index patch tests; existing changelog 2026-07-01 fixed note | verified by product tests |
| MCP tools expose names, descriptions, and input schemas to clients/models. | MCP tools specification, 2025-06-18: https://modelcontextprotocol.io/specification/2025-06-18/server/tools | verified by primary source |
| PostgreSQL primary keys uniquely identify rows and reject null values. | PostgreSQL constraints docs: https://www.postgresql.org/docs/current/ddl-constraints.html | verified by primary source |
| PostgreSQL identity columns generate values automatically from a sequence. | PostgreSQL identity columns docs: https://www.postgresql.org/docs/current/ddl-identity-columns.html | verified by primary source |
| Stripe describes idempotency keys as a way to retry requests without accidentally performing the same operation twice. | Stripe API docs: https://docs.stripe.com/api/idempotent_requests | verified by primary source |

## Table Stakes vs. Gap

Table stakes from existing Rowset content:

- Explain index columns and `rowset_id`.
- Tie row identity to MCP and REST by-index operations.
- Warn against mutable fields such as status, owner, title, price, or description.

Gap filled by this piece:

- A focused comparison of generated `rowset_id` and business keys.
- Operational guidance for retries, exports/imports, relationships, and migration.
- Copyable dataset-instruction blocks for both identity modes.

## Information Gain

The original element is a Rowset-specific operating framework for deciding between generated `rowset_id` and business keys across agent retries, export/import round trips, relationship targets, and persistent dataset instructions. Existing Rowset content explains index columns generally; this post isolates the generated-vs-business-key decision.

## Internal Links

Outbound from new post:

- `/docs/connect-mcp/`
- `/docs/dataset-api/`
- `/blog/choose-index-column-agent-rows`
- `/docs/design-schema/`
- `/blog/structure-dataset-instructions-ai-agents`
- `/docs/mcp-tools/`

Inbound added:

- `/blog/choose-index-column-agent-rows`
- `/docs/create-datasets/`
- `/blog/google-sheets-alternatives`

## Quality Gates

- Human usefulness: pass; decision table and templates help a real dataset-creation task.
- Product fit: pass; tied to Rowset dataset creation, MCP/REST by-index operations, relationships, exports, and instructions.
- AEO: pass; direct answer, decision table, FAQ, source-backed claims.
- Duplication: pass; adjacent to but not duplicative of the shipped index-column guide.
- Source integrity: pass; no fabricated metrics, quotes, or customer stories.
