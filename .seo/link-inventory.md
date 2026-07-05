# Rowset - Internal Link Inventory

> Every SEO sprint phase should pick links from this inventory and update it when a new page ships.

## Existing Pages

### Homepage + Core Marketing

| Slug | URL | Title / anchor candidate | Used by patterns |
|---|---|---|---|
| `/` | https://rowset.lvtd.dev/ | Rowset private datasets for AI agents | All |
| `/pricing` | https://rowset.lvtd.dev/pricing | Rowset pricing | Compare, alternatives, playbooks |
| `/use-cases` | https://rowset.lvtd.dev/use-cases | Rowset use cases | Use-case, playbooks |
| `/uses` | https://rowset.lvtd.dev/uses | Technology behind Rowset | Technical playbooks |
| `/blog/` | https://rowset.lvtd.dev/blog/ | Rowset Blog | Playbooks |
| `/llms.txt` | https://rowset.lvtd.dev/llms.txt | Rowset overview for agents | AI/agent discovery |
| `/SKILL.md` | https://rowset.lvtd.dev/SKILL.md | Rowset setup skill | Agent setup |

### Features and Docs

| Slug | URL | Title | Linked by |
|---|---|---|---|
| `/docs/getting-started/introduction/` | https://rowset.lvtd.dev/docs/getting-started/introduction/ | Getting started with Rowset | All |
| `/docs/features/datasets/` | https://rowset.lvtd.dev/docs/features/datasets/ | Working with datasets | Use-case, alternatives, playbooks |
| `/docs/features/public-previews/` | https://rowset.lvtd.dev/docs/features/public-previews/ | Public previews | Use-case, alternatives |
| `/docs/features/agent-discovery/` | https://rowset.lvtd.dev/docs/features/agent-discovery/ | Agent discovery | Use-case, playbooks |
| `/docs/features/mcp/` | https://rowset.lvtd.dev/docs/features/mcp/ | MCP access | Alternatives, playbooks |
| `/docs/features/agent-access/` | https://rowset.lvtd.dev/docs/features/agent-access/ | Agent access | Alternatives, use-case |
| `/docs/api-reference/introduction/` | https://rowset.lvtd.dev/docs/api-reference/introduction/ | Rowset API introduction | Alternatives, playbooks |
| `/docs/api-reference/user/` | https://rowset.lvtd.dev/docs/api-reference/user/ | User API | Setup content |
| `/docs/api-reference/projects/` | https://rowset.lvtd.dev/docs/api-reference/projects/ | Project API | Use-case content |
| `/docs/api-reference/datasets/` | https://rowset.lvtd.dev/docs/api-reference/datasets/ | Dataset API | All |

### Existing Use-Case Pages

| Slug | URL | Title | Linked by |
|---|---|---|---|
| `/use-cases/personal-crm` | https://rowset.lvtd.dev/use-cases/personal-crm | Agent-managed personal CRM | Use-case, alternatives |
| `/use-cases/agent-task-board` | https://rowset.lvtd.dev/use-cases/agent-task-board | Agent task board | Use-case, alternatives |
| `/use-cases/feedback-triage` | https://rowset.lvtd.dev/use-cases/feedback-triage | Feedback triage | Use-case, alternatives |
| `/use-cases/content-pipeline` | https://rowset.lvtd.dev/use-cases/content-pipeline | Content pipeline | Use-case, playbooks |
| `/use-cases/product-inventory-catalog` | https://rowset.lvtd.dev/use-cases/product-inventory-catalog | Product or inventory catalog | Use-case, alternatives |
| `/use-cases/bug-qa-tracker` | https://rowset.lvtd.dev/use-cases/bug-qa-tracker | Bug or QA tracker | Use-case, playbooks |

### Blog Posts

| Slug | URL | Title | Topic | Linked by |
|---|---|---|---|---|
| `/blog/agent-managed-datasets` | https://rowset.lvtd.dev/blog/agent-managed-datasets | What is an agent-managed dataset? | agent workflows, datasets, MCP | Dataset API docs, MCP docs |
| `/blog/mcp-vs-rest-ai-agents` | https://rowset.lvtd.dev/blog/mcp-vs-rest-ai-agents | When should an AI agent use MCP instead of REST? | MCP, REST, agent workflows | MCP docs, Agent access docs, agent-managed datasets blog |
| `/blog/choose-index-column-agent-rows` | https://rowset.lvtd.dev/blog/choose-index-column-agent-rows | How to choose an index column for agent-managed rows | index columns, stable row identity, agent workflows | Dataset API docs, MCP docs, agent-managed datasets blog |

## SEO-Sprint-Generated Pages

### `/alternatives/[slug]`

| Slug | Ships in phase | URL | Inbound links from | Outbound links to |
|---|---|---|---|---|
| `airtable` | Phase 3 | `/alternatives/airtable` | homepage, MCP docs, Dataset API docs | pricing, signup, MCP docs, Dataset API, Agent access, agent task board, feedback triage |
| `google-sheets` | Phase 4 | `/alternatives/google-sheets` | TBD | homepage, pricing, use cases, Dataset API |
| `baserow` | Phase 6 | `/alternatives/baserow` | TBD | homepage, MCP docs, Dataset API |
| `nocodb` | Phase 7 | `/alternatives/nocodb` | TBD | homepage, MCP docs, Dataset API |

### `/use-cases/[slug]` or Future `/for/[slug]`

| Slug | Ships in phase | URL | Inbound links from | Outbound links to |
|---|---|---|---|---|
| `ai-agent-crm` | existing/Phase 1 expansion | `/use-cases/personal-crm` | homepage, use-cases index | Dataset API, MCP docs, Agent access |
| `agent-task-board` | existing/Phase 1 expansion | `/use-cases/agent-task-board` | homepage, use-cases index | Dataset API, MCP docs, projects docs |
| `feedback-triage` | existing/Phase 1 expansion | `/use-cases/feedback-triage` | homepage, use-cases index | public previews, Dataset API |
| `content-pipeline` | existing/Phase 1 expansion | `/use-cases/content-pipeline` | homepage, use-cases index | projects docs, Dataset API |

### `/compare/[slug]`

| Slug | Ships in phase | URL | Inbound links from | Outbound links to |
|---|---|---|---|---|
| `rowset-vs-airtable` | Phase 9 | `/compare/rowset-vs-airtable` | TBD | `/alternatives/airtable`, pricing, MCP docs |

### `/playbooks/[slug]`

| Slug | Ships in phase | URL | Inbound links from | Outbound links to |
|---|---|---|---|---|
| `database-mcp-server` | Phase 2 | `/playbooks/database-mcp-server` | MCP docs, Dataset API docs | MCP docs, Dataset API, Agent access, pricing, personal CRM, agent task board, feedback triage |
| `spreadsheet-database-for-ai-agents` | Phase 5 | `/playbooks/spreadsheet-database-for-ai-agents` | TBD | Google Sheets alternatives, Dataset API, MCP docs |
| `connect-ai-agent-to-dataset-api` | Phase 8 | `/playbooks/connect-ai-agent-to-dataset-api` | TBD | MCP docs, Dataset API, Agent access |

## Anchor-Text Variations

- Rowset private dataset backend
- MCP dataset backend
- REST dataset API
- hosted MCP access
- Rowset Dataset API
- API-backed datasets
- agent-managed dataset
- structured rows for agents
- private dataset layer for AI agents
- agent-operated row store
- agent-managed personal CRM
- agent task board
- feedback triage workflow
- public read-only previews
- Rowset setup prompt
- agent discovery guide
- MCP vs REST for AI agents
- when to use MCP instead of REST
- Rowset MCP and REST access
- agent API decision guide
- choose an index column for agent-managed rows
- stable row identity for agents
- Rowset index column guide
- generated rowset_id fallback
- by-index row operations
