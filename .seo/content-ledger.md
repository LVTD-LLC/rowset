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
| 2026-07-11 | Best NocoDB alternatives for AI-agent-managed datasets | comparison/listicle | `/blog/nocodb-alternatives` | nocodb alternatives | 50 | 14 | Dataset API, MCP docs, index-column guide, Rowset rowset_id vs business keys | #TBD |
| 2026-07-12 | How to connect an AI agent to the Rowset Dataset API | how-to | `/blog/connect-ai-agent-to-dataset-api` | connect AI agent to Dataset API | unmeasured | n/a | Dataset API, MCP docs, agent access, agent discovery, index-column guide, dataset-instructions guide | #TBD |

---

## Candidate Backlog

| Rank | Candidate | Proposed type | Target keyword | Vol | KD | Intent | Score | Notes / angle |
|---|---|---|---|---|---|---|---|---|
| 1 | Rowset rowset_id vs business keys | comparison | generated id vs natural key | unmeasured | n/a | decision | 19 | Keep decision angle open while moving into setup and explain pages. |
| 2 | Best Baserow alternatives for AI-agent-managed datasets | comparison/listicle | baserow alternatives | 70 | 0 | commercial/informational | 18 | Next alternatives expansion requires no duplicate of same audience; this is already queued as prior phase but keeps the lane warm. |
| 3 | How to choose an index column for agent-managed rows | how-to | dataset index column | estimated | n/a | process | 17 | Product-native tutorial for identity stability and row mutation safety. |
| 4 | spreadsheet database for AI agents | explanation | spreadsheet database | 170 | 20 | informational | 15 | Helps map when spreadsheet-style tools are the right fit before a trust-first recommendation. |
| 5 | Relationship modeling for agent-managed datasets | how-to | agent dataset relationships | unmeasured | n/a | operational/setup | 14 | Natural next product-native post after Dataset API setup; explain when one dataset should reference another. |

---

## Coverage Map

| Cluster / theme | Pieces shipped | Gaps still open |
|---|---|---|
| Agent-managed datasets | `/blog/agent-managed-datasets`, `/blog/choose-index-column-agent-rows`, `/blog/structure-dataset-instructions-ai-agents`, `/blog/rowset-id-vs-business-keys` | Relationship modeling guide; generated-index migration patterns |
| MCP and Dataset API | `/blog/mcp-vs-rest-ai-agents`, `/blog/connect-ai-agent-to-dataset-api` | Relationship modeling guide; REST/MCP setup examples with concrete datasets |
| Spreadsheet/database alternatives | `/blog/airtable-alternatives`, `/blog/google-sheets-alternatives`, `/blog/baserow-alternatives`, `/blog/nocodb-alternatives` | Spreadsheet database explanation and `/compare/rowset-vs-airtable` |

---

## Notes

- **DR cap:** Ahrefs DR is unavailable; use DataForSEO KD/backlink signals in `.seo/keyword-research.json`.
- **No duplication:** this piece intentionally avoids the sprint roadmap's `/alternatives`, `/compare`, `/how-to`, and `/explanations` targets.
- **One piece per run:** this ledger grows by one shipped row per `seo-content` invocation.
