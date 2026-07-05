# Rowset - Content Ledger

> The memory of the content engine. Read first on every `seo-content` run: the **Shipped** table is the dedup record, and the **Candidate backlog** is the scored shortlist for the next run.

---

## Shipped

| Date | Title | Type | Slug / URL | Target keyword | Vol | KD | Primary internal links | Commit / PR |
|---|---|---|---|---|---|---|---|---|
| 2026-07-04 | What is an agent-managed dataset? | definition | `/blog/agent-managed-datasets` | agent-managed dataset | unmeasured | n/a | MCP access, Dataset API, public previews, content pipeline | #191 |
| 2026-07-05 | When should an AI agent use MCP instead of REST? | comparison | `/blog/mcp-vs-rest-ai-agents` | MCP vs REST for AI agents | estimated | n/a | MCP access, Dataset API, Agent access, agent-managed datasets | #195 |
| 2026-07-05 | How to choose an index column for agent-managed rows | how-to | `/blog/choose-index-column-agent-rows` | dataset index column | estimated | n/a | MCP access, Dataset API, Agent discovery, agent-managed datasets, MCP vs REST | pending |

---

## Candidate Backlog

| Rank | Candidate | Proposed type | Target keyword | Vol | KD | Intent | Score | Notes / angle |
|---|---|---|---|---|---|---|---|---|
| 1 | How to choose an index column for agent-managed rows | how-to | dataset index column | estimated | n/a | process | 16 | Shipped in this run as a product-native tutorial that supports Dataset API docs and reduces agent row-update mistakes. |
| 2 | How to structure dataset instructions for AI agents | how-to | AI agent dataset instructions | unmeasured | n/a | process/AEO | 15 | Product-native guide for using `instructions`, `metadata`, column descriptions, and project context without duplicating API docs. |
| 3 | Rowset `rowset_id` vs business keys | comparison | generated id vs natural key | unmeasured | n/a | decision | 14 | Narrow follow-up for generated indexes, upstream IDs, exports, and relationship tradeoffs. |

---

## Coverage Map

| Cluster / theme | Pieces shipped | Gaps still open |
|---|---|---|
| Agent-managed datasets | `/blog/agent-managed-datasets`, `/blog/choose-index-column-agent-rows` | Dataset instructions tutorial |
| MCP and Dataset API | `/blog/mcp-vs-rest-ai-agents` | Sprint Phase 1 docs strengthening, Phase 2 database MCP server playbook |
| Spreadsheet/database alternatives | - | Sprint alternatives and playbooks |

---

## Notes

- **DR cap:** Ahrefs DR is unavailable; use DataForSEO KD/backlink signals in `.seo/keyword-research.json`.
- **No duplication:** this piece intentionally avoids the sprint roadmap's `/alternatives`, `/compare`, and `/playbooks` targets.
- **One piece per run:** this ledger grows by one shipped row per `seo-content` invocation.
