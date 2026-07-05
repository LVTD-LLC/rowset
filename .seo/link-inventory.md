# Rowset - Internal Link Inventory

> Every SEO sprint phase should pick links from this inventory and update it when a new page ships.

## Existing Pages

### Homepage + Core Marketing

| Slug | URL | Title / anchor candidate | Used by patterns |
|---|---|---|---|
| `/` | https://rowset.lvtd.dev/ | Rowset private datasets for AI agents | All |
| `/pricing` | https://rowset.lvtd.dev/pricing | Rowset pricing | Compare, alternatives, long-form guides |
| `/how-to` | https://rowset.lvtd.dev/how-to | Rowset how-to guides | Use-case guides, long-form guides |
| `/uses` | https://rowset.lvtd.dev/uses | Technology behind Rowset | Technical explanations |
| `/blog/` | https://rowset.lvtd.dev/blog/ | Rowset Blog | Long-form guides |
| `/llms.txt` | https://rowset.lvtd.dev/llms.txt | Rowset overview for agents | AI/agent discovery |
| `/SKILL.md` | https://rowset.lvtd.dev/SKILL.md | Rowset setup skill | Agent setup |

### Features and Docs

| Slug | URL | Title | Linked by |
|---|---|---|---|
| `/tutorials/first-agent-dataset/` | https://rowset.lvtd.dev/tutorials/first-agent-dataset/ | Getting started with Rowset | All |
| `/explanations/datasets/` | https://rowset.lvtd.dev/explanations/datasets/ | Working with datasets | Use-case guides, alternatives, long-form guides |
| `/how-to/share-public-preview/` | https://rowset.lvtd.dev/how-to/share-public-preview/ | Public previews | Use-case, alternatives |
| `/how-to/help-agents-discover-rowset/` | https://rowset.lvtd.dev/how-to/help-agents-discover-rowset/ | Agent discovery | Use-case guides, long-form guides |
| `/how-to/connect-mcp/` | https://rowset.lvtd.dev/how-to/connect-mcp/ | MCP access | Alternatives, long-form guides |
| `/how-to/configure-agent-access/` | https://rowset.lvtd.dev/how-to/configure-agent-access/ | Agent access | Alternatives, use-case |
| `/docs/api-overview/` | https://rowset.lvtd.dev/docs/api-overview/ | Rowset API introduction | Alternatives, long-form guides |
| `/docs/user-api/` | https://rowset.lvtd.dev/docs/user-api/ | User API | Setup content |
| `/docs/project-api/` | https://rowset.lvtd.dev/docs/project-api/ | Project API | Use-case content |
| `/docs/dataset-api/` | https://rowset.lvtd.dev/docs/dataset-api/ | Dataset API | All |

### Existing Use-Case Pages

| Slug | URL | Title | Linked by |
|---|---|---|---|
| `/how-to/personal-crm` | https://rowset.lvtd.dev/how-to/personal-crm | Agent-managed personal CRM | Use-case, alternatives |
| `/how-to/agent-task-board` | https://rowset.lvtd.dev/how-to/agent-task-board | Agent task board | Use-case, alternatives |
| `/how-to/feedback-triage` | https://rowset.lvtd.dev/how-to/feedback-triage | Feedback triage | Use-case, alternatives |
| `/how-to/content-pipeline` | https://rowset.lvtd.dev/how-to/content-pipeline | Content pipeline | Use-case guides, long-form guides |
| `/how-to/product-inventory-catalog` | https://rowset.lvtd.dev/how-to/product-inventory-catalog | Product or inventory catalog | Use-case, alternatives |
| `/how-to/bug-qa-tracker` | https://rowset.lvtd.dev/how-to/bug-qa-tracker | Bug or QA tracker | Use-case guides, long-form guides |

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
| `airtable` | Phase 3 | `/alternatives/airtable/` | landing page, how-to index | pricing, signup, MCP docs, Dataset API |
| `google-sheets` | Phase 4 | `/alternatives/google-sheets` | TBD | homepage, pricing, use cases, Dataset API |
| `baserow` | Phase 6 | `/alternatives/baserow` | TBD | homepage, MCP docs, Dataset API |
| `nocodb` | Phase 7 | `/alternatives/nocodb` | TBD | homepage, MCP docs, Dataset API |

### `/how-to/[slug]` or Future `/for/[slug]`

| Slug | Ships in phase | URL | Inbound links from | Outbound links to |
|---|---|---|---|---|
| `ai-agent-crm` | existing/Phase 1 expansion | `/how-to/personal-crm` | homepage, how-to index | Dataset API, MCP docs, Agent access |
| `agent-task-board` | existing/Phase 1 expansion | `/how-to/agent-task-board` | homepage, how-to index | Dataset API, MCP docs, projects docs |
| `feedback-triage` | existing/Phase 1 expansion | `/how-to/feedback-triage` | homepage, how-to index | public previews, Dataset API |
| `content-pipeline` | existing/Phase 1 expansion | `/how-to/content-pipeline` | homepage, how-to index | projects docs, Dataset API |

### `/compare/[slug]`

| Slug | Ships in phase | URL | Inbound links from | Outbound links to |
|---|---|---|---|---|
| `rowset-vs-airtable` | Phase 9 | `/compare/rowset-vs-airtable` | TBD | `/alternatives/airtable`, pricing, MCP docs |

### Long-Form Explanations and How-To Guides

| Slug | Ships in phase | URL | Inbound links from | Outbound links to |
|---|---|---|---|---|
| `database-mcp-server` | Phase 2 | `/explanations/database-mcp-server` | MCP docs, Dataset API docs | MCP docs, Dataset API, Agent access, pricing, personal CRM, agent task board, feedback triage |
| `spreadsheet-database-for-ai-agents` | Phase 5 | `/explanations/spreadsheet-database-for-ai-agents` | TBD | Google Sheets alternatives, Dataset API, MCP docs |
| `connect-ai-agent-to-dataset-api` | Phase 8 | `/how-to/connect-ai-agent-to-dataset-api` | TBD | MCP docs, Dataset API, Agent access |

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
