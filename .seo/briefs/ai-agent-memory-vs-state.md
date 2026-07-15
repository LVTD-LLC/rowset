# SEO Brief: AI agent memory vs structured state

## Selection

- **Date:** 2026-07-14
- **Chosen candidate:** AI agent memory vs structured operational state
- **Type:** comparison / decision guide
- **Target keyword:** AI agent memory vs state
- **Volume / KD:** unmeasured / n/a; DataForSEO runtime credentials and the installed skill script were unavailable during this refresh
- **SERP signal:** live search results include decision guides, database comparisons, framework docs, and recent research on agent memory. The dominant format is a long comparison with a decision framework.
- **Why this topic:** The current backlog's first three rows have already shipped, while its remaining measured topic belongs to a planned explanation page. This is the highest-priority blog-safe gap after excluding shipped posts, docs, and sprint-owned pages.
- **Slug:** `/blog/ai-agent-memory-vs-state`

## Refreshed Candidate Backlog

| Rank | Candidate | Type | Winnability | Traffic | Conversion | Strategic | Effort | Score |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | AI agent memory vs structured state | comparison / decision guide | 3 | 4 | 3 | 5 | 4 | 19 |
| 2 | How to make AI-agent data updates idempotent | how-to | 3 | 2 | 4 | 5 | 4 | 18 |
| 3 | How to share agent-managed datasets safely | decision guide | 4 | 2 | 4 | 4 | 4 | 18 |

## Product-Led SEO Check

- **User job:** Help builders decide where an agent should keep preferences, conversation context, workflow records, and current business data.
- **Product surface:** Rowset datasets, stable index columns, dataset instructions, schema, MCP tools, REST endpoints, hybrid search, and read-only public previews.
- **Business outcome:** Qualifies readers who need an operational dataset layer rather than a memory product, then routes them to the dataset guide, MCP setup, use cases, and pricing.
- **Moat:** Rowset can explain the boundary from a working product model: canonical Postgres-backed rows remain the source of truth while optional hybrid search is a retrieval index. Generic memory articles rarely make the mutation and human-review boundary concrete.

## AI SEO / AEO Check

- Direct verdict appears in the opening paragraph.
- The comparison table and "authoritative lookup" test are self-contained answer blocks.
- Claims are sourced to official LangGraph, MCP, PostgreSQL, and Rowset documentation.
- Entity coverage: AI agent memory, short-term memory, long-term memory, checkpoints, semantic search, operational state, canonical records, index columns, MCP tools, REST, Rowset, public previews.
- Freshness: published 2026-07-14; external sources checked 2026-07-14.
- Schema: the existing blog renderer emits `BlogPosting` with published/modified dates, author, publisher, canonical URL, keywords, and article body. The FAQ is kept as semantic HTML because the current blog content model does not extract per-post `FAQPage` data.

## Claim Ledger

| Claim | Source | Tier | Date | Status |
|---|---|---|---|---|
| LangGraph treats short-term memory as thread-scoped state and long-term memory as cross-thread user/application data. | https://docs.langchain.com/oss/python/concepts/memory; https://langchain-ai.github.io/langgraph/agents/memory/ | primary external | checked 2026-07-14 | verified |
| LangGraph checkpointers persist graph state, while stores persist long-term memory outside graph state. | https://docs.langchain.com/oss/python/langgraph/persistence; https://langchain-ai.github.io/langgraph/reference/checkpoints/ | primary external | checked 2026-07-14 | verified |
| Semantic memory retrieval can use embeddings and similarity search. | https://langchain-ai.github.io/langgraph/agents/memory/; https://docs.langchain.com/oss/python/concepts/memory | primary external | checked 2026-07-14 | verified |
| MCP tools are schema-defined operations that models can discover and invoke against external systems. | https://modelcontextprotocol.io/docs/learn/server-concepts; https://modelcontextprotocol.io/specification/2025-06-18/server/tools | primary external | checked 2026-07-14 | verified |
| MCP resources provide structured read access, while tools can perform actions such as database writes and API calls. | https://modelcontextprotocol.io/docs/learn/server-concepts; https://modelcontextprotocol.io/specification/2025-06-18/server/index | primary external | checked 2026-07-14 | verified |
| PostgreSQL primary keys identify rows and require unique, non-null values. | https://www.postgresql.org/docs/current/ddl-constraints.html; `apps/pages/content/docs/datasets.md` | primary external + product | checked 2026-07-14 | verified |
| Rowset datasets expose headers, index columns, schema, instructions, metadata, relationships, and row operations through MCP/REST. | `apps/pages/content/docs/datasets.md`; `apps/pages/content/docs/dataset-api.md`; `apps/pages/content/docs/mcp-tools.md` | primary product | 2026-07-14 repo | verified |
| Rowset's vector/lexical search returns canonical rows; Postgres remains the source of truth. | `apps/pages/content/docs/dataset-api.md`; `apps/pages/content/docs/mcp-tools.md`; `apps/pages/content/docs/work-with-rows.md` | primary product | 2026-07-14 repo | verified |
| Rowset public previews are read-only human review surfaces, not agent authentication paths. | `apps/pages/content/docs/mcp-rest-public-previews.md`; `apps/pages/content/docs/datasets.md` | primary product | 2026-07-14 repo | verified |
| Rowset currently offers a 7-day full-product trial and Pro at $50 per month. | `apps/pages/content/public/pricing.md`; `frontend/templates/pages/pricing.html` | primary product | 2026-07-14 repo | verified |

## Table Stakes

- Define memory, framework/runtime state, and structured operational state.
- Compare storage purpose, lookup style, mutation model, and examples.
- Explain when the same workflow needs more than one layer.
- Cover conversation history, preferences, tasks, CRM rows, catalogs, and audit/history data.
- Address vector search without presenting it as a canonical row identity mechanism.
- Give a practical implementation checklist and decision examples.

## Information Gain

The post introduces the **authoritative lookup test**: ask what a human should inspect to settle a disagreement. If the answer is a current keyed record, keep it in structured operational state; if the answer is contextual recollection whose relevance varies by situation, keep it in memory. The framework then separates recall, execution checkpoints, operational records, and audit history without pretending one storage layer should own all four.

## Internal Links

- `/blog/agent-managed-datasets`
- `/docs/datasets`
- `/docs/connect-mcp`
- `/docs/dataset-api`
- `/docs/work-with-rows`
- `/blog/choose-index-column-agent-rows`
- `/use-cases/agent-task-board`
- `/use-cases/personal-crm`
- `/pricing`

## Quality Gates

- Information gain: pass; authoritative lookup test and four-layer model are present.
- Citation coverage: pass; no invented metrics, customers, or performance claims.
- AEO: pass; direct answer, extractable table, decision rules, FAQ, dated frontmatter.
- Product-led SEO: pass; useful Rowset surface, credible angle, clear next-step paths.
- Voice: direct, technical, calm, concrete; forbidden phrases avoided.
