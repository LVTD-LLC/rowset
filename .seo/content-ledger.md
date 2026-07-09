# Rowset - Content Ledger

> The memory of the content engine. Read first on every `seo-content` run: the **Shipped** table is the dedup record, and the **Candidate backlog** is the scored shortlist for the next run.

---

## Shipped

| Date | Title | Type | Slug / URL | Target keyword | Vol | KD | Primary internal links | Commit / PR |
|---|---|---|---|---|---|---|---|---|
| 2026-07-04 | What is an agent-managed dataset? | definition | `/blog/agent-managed-datasets` | agent-managed dataset | unmeasured | n/a | MCP access, Dataset API, public previews, content pipeline | #191 |
| 2026-07-05 | When should an AI agent use MCP instead of REST? | comparison | `/blog/mcp-vs-rest-ai-agents` | MCP vs REST for AI agents | estimated | n/a | MCP access, Dataset API, Agent access, agent-managed datasets | #195 |
| 2026-07-05 | How to choose an index column for agent-managed rows | how-to | `/blog/choose-index-column-agent-rows` | dataset index column | estimated | n/a | MCP access, Dataset API, Agent discovery, agent-managed datasets, MCP vs REST | #198 |
| 2026-07-05 | Best Airtable alternatives for AI-agent-managed datasets | comparison/listicle | `/blog/airtable-alternatives` | airtable alternatives | 720 | 0 | MCP access, Dataset API, public previews, index-column guide, agent-managed datasets | #207 |
| 2026-07-06 | Best Google Sheets alternatives for AI-agent-managed datasets | comparison/listicle | `/blog/google-sheets-alternatives` | google sheets alternatives | 480 | 0 | MCP access, Dataset API, agent access, Airtable alternatives, index-column guide, agent use cases | #209 |
| 2026-07-07 | How to structure dataset instructions for AI agents | how-to | `/blog/structure-dataset-instructions-ai-agents` | AI agent dataset instructions | unmeasured | n/a | MCP access, Dataset API, schema design, content pipeline, feedback triage, index-column guide | #219 |
| 2026-07-08 | Rowset rowset_id vs business keys: which should agents use? | comparison/decision guide | `/blog/rowset-id-vs-business-keys` | Rowset rowset_id | unmeasured | n/a | Dataset API, MCP tools, schema design, index-column guide, dataset-instructions guide | #227 |
| 2026-07-09 | Best Baserow alternatives for AI-agent-managed datasets | comparison/listicle | `/blog/baserow-alternatives` | baserow alternatives | 70 | 0 | MCP access, Dataset API, Baserow API, Airtable alternatives, Google Sheets alternatives, row identity guide | #233 |

---

## Candidate Backlog

| Rank | Candidate | Proposed type | Target keyword | Vol | KD | Intent | Score | Notes / angle |
|---|---|---|---|---|---|---|---|---|
| 1 | How to choose an index column for agent-managed rows | how-to | dataset index column | estimated | n/a | process | 16 | Shipped in this run as a product-native tutorial that supports Dataset API docs and reduces agent row-update mistakes. |
| 2 | How to structure dataset instructions for AI agents | how-to | AI agent dataset instructions | unmeasured | n/a | process/AEO | 15 | Shipped in this run as a product-native guide for using `instructions`, `metadata`, column descriptions, and project context without duplicating API docs. |
| 3 | Rowset `rowset_id` vs business keys | comparison | generated id vs natural key | unmeasured | n/a | decision | 14 | Shipped in this run as a focused decision guide for generated identity, business keys, exports/imports, retries, and relationships. |
| 4 | Best Google Sheets alternatives for AI-agent-managed datasets | comparison/listicle | google sheets alternatives | 480 | 0 | commercial/informational | 18 | Shipped in this run from SEO sprint Phase 4; product-led angle is Sheets for humans vs Rowset for trusted agents operating private MCP/REST rows. |
| 5 | Best Baserow alternatives for AI-agent-managed datasets | comparison/listicle | baserow alternatives | 70 | 0 | commercial/informational | 17 | Shipped in this run as a narrow comparison for Baserow-style database workspaces vs Rowset's private MCP/REST datasets for trusted agents. |

---

## Coverage Map

| Cluster / theme | Pieces shipped | Gaps still open |
|---|---|---|
| Agent-managed datasets | `/blog/agent-managed-datasets`, `/blog/choose-index-column-agent-rows`, `/blog/structure-dataset-instructions-ai-agents`, `/blog/rowset-id-vs-business-keys` | Relationship modeling guide; generated-index migration patterns |
| MCP and Dataset API | `/blog/mcp-vs-rest-ai-agents` | Sprint Phase 1 docs strengthening, Phase 2 database MCP server explanation |
| Spreadsheet/database alternatives | `/blog/airtable-alternatives`, `/blog/google-sheets-alternatives`, `/blog/baserow-alternatives` | NocoDB blog post; spreadsheet database explanation |

---

## Notes

- **DR cap:** Ahrefs DR is unavailable; use DataForSEO KD/backlink signals in `.seo/keyword-research.json`.
- **No duplication:** this piece intentionally avoids the sprint roadmap's `/alternatives`, `/compare`, `/how-to`, and `/explanations` targets.
- **One piece per run:** this ledger grows by one shipped row per `seo-content` invocation.
