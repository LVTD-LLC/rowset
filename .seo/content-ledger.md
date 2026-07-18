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
| 2026-07-13 | How to model relationships between agent-managed datasets | how-to/decision guide | `/blog/relationship-modeling-agent-datasets` | agent dataset relationships | unmeasured | n/a | Relationship docs, Dataset API, MCP access, index-column guide, dataset-instructions guide, content pipeline | #TBD |
| 2026-07-14 | AI agent memory vs structured state: what goes where? | comparison/decision guide | `/blog/ai-agent-memory-vs-state` | AI agent memory vs state | unmeasured | n/a | Agent-managed datasets, datasets docs, MCP access, Dataset API, task board, personal CRM | #262 |
| 2026-07-15 | How to make AI-agent data updates idempotent | how-to / operational decision guide | `/blog/idempotent-ai-agent-updates` | AI agent idempotent operations | unmeasured | n/a | Work with rows, Dataset API, MCP access, index-column guide, dataset-instructions guide, task board | #263 |
| 2026-07-15 | Rowset vs Airtable: Which Fits AI Agents? (2026) | product comparison | `/vs/airtable` | Rowset vs Airtable | unmeasured | n/a | Airtable alternatives, pricing, MCP docs, Dataset API, public previews, index-column guide | #277 |
| 2026-07-15 | Rowset vs Google Sheets for AI Agents (2026) | product comparison | `/vs/google-sheets` | Rowset vs Google Sheets | unmeasured | n/a | Google Sheets alternatives, pricing, MCP docs, Dataset API, public previews, index-column guide | #280 |
| 2026-07-16 | How to share AI-agent data safely | security decision guide | `/blog/share-ai-agent-data-safely` | share AI agent data | unmeasured | n/a | MCP access, Dataset API, agent access, public previews, exports, relationship modeling, feedback triage | #281 |
| 2026-07-18 | Human-in-the-Loop AI Agents: A Practical Workflow | how-to / operational decision guide | `/blog/human-in-the-loop-ai-agents` | human in the loop AI agents | 70 | 11 | MCP access, Dataset API, schema design, dataset instructions, idempotent updates, safe sharing, pricing | #310 |

---

## Candidate Backlog

| Rank | Candidate | Proposed type | Target keyword | Vol | KD | Intent | Score | Notes / angle |
|---|---|---|---|---|---|---|---|---|
| 1 | AI agent memory vs structured state | comparison/decision guide | AI agent memory vs state | unmeasured | n/a | architecture/decision | shipped | Shipped 2026-07-14 as `/blog/ai-agent-memory-vs-state`. |
| 2 | How to make AI-agent data updates idempotent | how-to | AI agent idempotent operations | unmeasured | n/a | operational/setup | shipped | Shipped 2026-07-15 as `/blog/idempotent-ai-agent-updates`. |
| 3 | How to share agent-managed datasets safely | decision guide | share AI agent data | unmeasured | n/a | security/decision | shipped | Shipped 2026-07-16 as `/blog/share-ai-agent-data-safely`. |
| 4 | spreadsheet database for AI agents | explanation | spreadsheet database | 170 | 20 | informational | 15 | Reserved for the sprint-owned explanation page; do not duplicate as a blog post. |
| 5 | Human-in-the-loop AI agents | how-to / operational decision guide | human in the loop AI agents | 70 | 11 | informational / implementation | shipped | Shipped 2026-07-18 as `/blog/human-in-the-loop-ai-agents`. |
| 6 | AI agent audit trail | implementation guide | AI audit trail | 40 | n/a | commercial / implementation | 17 | Strong product fit, but narrower demand and substantial overlap with the selected HITL workflow. |
| 7 | Database for AI agents | decision guide | database for AI agents | 10 | 7 | commercial | 16 | Winnable but overlaps existing agent-managed-dataset and memory-vs-state coverage. |

---

## Coverage Map

| Cluster / theme | Pieces shipped | Gaps still open |
|---|---|---|
| Agent-managed datasets | `/blog/agent-managed-datasets`, `/blog/choose-index-column-agent-rows`, `/blog/structure-dataset-instructions-ai-agents`, `/blog/rowset-id-vs-business-keys`, `/blog/relationship-modeling-agent-datasets`, `/blog/ai-agent-memory-vs-state`, `/blog/idempotent-ai-agent-updates`, `/blog/share-ai-agent-data-safely`, `/blog/human-in-the-loop-ai-agents` | Generated-index migration patterns; audit-history implementation details |
| MCP and Dataset API | `/blog/mcp-vs-rest-ai-agents`, `/blog/connect-ai-agent-to-dataset-api`, `/blog/relationship-modeling-agent-datasets` | REST/MCP setup examples with concrete datasets |
| Spreadsheet/database alternatives | `/blog/airtable-alternatives`, `/blog/google-sheets-alternatives`, `/blog/baserow-alternatives`, `/blog/nocodb-alternatives`, `/vs/airtable`, `/vs/google-sheets` | Spreadsheet database explanation |

---

## Notes

- **DR cap:** Ahrefs DR is unavailable; use DataForSEO KD/backlink signals in `.seo/keyword-research.json`.
- **No duplication:** this piece intentionally avoids the sprint roadmap's `/alternatives`, `/compare`, `/how-to`, and `/explanations` targets.
- **One piece per run:** this ledger grows by one shipped row per `seo-content` invocation.
