# Rowset - Content Ledger

> The memory of the content engine. Read first on every `seo-content` run: the **Shipped** table is the dedup record, and the **Candidate backlog** is the scored shortlist for the next run.

---

## Shipped

| Date | Title | Type | Slug / URL | Target keyword | Vol | KD | Primary internal links | Commit / PR |
|---|---|---|---|---|---|---|---|---|
| 2026-07-04 | What is an agent-managed dataset? | definition | `/blog/agent-managed-datasets` | agent-managed dataset | unmeasured | n/a | MCP access, Dataset API, public previews, content pipeline | #191 |

---

## Candidate Backlog

| Rank | Candidate | Proposed type | Target keyword | Vol | KD | Intent | Score | Notes / angle |
|---|---|---|---|---|---|---|---|---|
| 1 | What is an agent-managed dataset? | definition | agent-managed dataset | unmeasured | n/a | informational/AEO | 19 | Shipped in this run as a foundational concept page that supports Dataset API, MCP, and future playbooks without duplicating the sprint roadmap. |
| 2 | When should an AI agent use MCP instead of REST? | comparison | MCP vs REST for AI agents | estimated | n/a | decision | 17 | Useful companion to MCP docs; avoid if Phase 2/8 playbooks already cover it deeply. |
| 3 | How to choose an index column for agent-managed rows | how-to | dataset index column | estimated | n/a | process | 16 | Product-native tutorial that could support Dataset API docs and reduce agent row-update mistakes. |

---

## Coverage Map

| Cluster / theme | Pieces shipped | Gaps still open |
|---|---|---|
| Agent-managed datasets | `/blog/agent-managed-datasets` | Index-column tutorial, MCP vs REST decision page |
| MCP and Dataset API | - | Sprint Phase 1 docs strengthening, Phase 2 database MCP server playbook |
| Spreadsheet/database alternatives | - | Sprint alternatives and playbooks |

---

## Notes

- **DR cap:** Ahrefs DR is unavailable; use DataForSEO KD/backlink signals in `.seo/keyword-research.json`.
- **No duplication:** this piece intentionally avoids the sprint roadmap's `/alternatives`, `/compare`, and `/playbooks` targets.
- **One piece per run:** this ledger grows by one shipped row per `seo-content` invocation.
