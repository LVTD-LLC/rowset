# Rowset - Internal Link Inventory

> Every SEO sprint phase should pick links from this inventory and update it when a new page ships.

## Existing pages

### Homepage + core marketing

| Slug | URL | Title / anchor candidate | Used by patterns |
|---|---|---|---|
| `/` | https://rowset.lvtd.dev/ | Rowset private datasets for AI agents | All |
| `/pricing` | https://rowset.lvtd.dev/pricing | Rowset pricing | Compare, alternatives, playbooks |
| `/use-cases` | https://rowset.lvtd.dev/use-cases | Rowset use cases | Use-case, playbooks |
| `/uses` | https://rowset.lvtd.dev/uses | Rowset technology stack | Technical playbooks |
| `/blog/` | https://rowset.lvtd.dev/blog/ | Rowset Blog | Playbooks |

### Features and docs

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

### Existing use-case pages

| Slug | URL | Title | Linked by |
|---|---|---|---|
| `/use-cases/personal-crm` | https://rowset.lvtd.dev/use-cases/personal-crm | Agent-managed personal CRM | Use-case, alternatives |
| `/use-cases/agent-task-board` | https://rowset.lvtd.dev/use-cases/agent-task-board | Agent task board | Use-case, alternatives |
| `/use-cases/feedback-triage` | https://rowset.lvtd.dev/use-cases/feedback-triage | Feedback triage | Use-case, alternatives |
| `/use-cases/content-pipeline` | https://rowset.lvtd.dev/use-cases/content-pipeline | Content pipeline | Use-case, playbooks |
| `/use-cases/product-inventory-catalog` | https://rowset.lvtd.dev/use-cases/product-inventory-catalog | Product or inventory catalog | Use-case, alternatives |
| `/use-cases/bug-qa-tracker` | https://rowset.lvtd.dev/use-cases/bug-qa-tracker | Bug or QA tracker | Use-case, playbooks |

### Blog posts

| Slug | URL | Title | Topic | Linked by |
|---|---|---|---|---|
| `/blog/openclaw-infisical-smoke-test-2026-05-14` | https://rowset.lvtd.dev/blog/openclaw-infisical-smoke-test-2026-05-14 | OpenClaw Infisical Smoke Test | test post | none |

## SEO-sprint-generated pages

### `/alternatives/[slug]`

| Slug | Ships in phase | URL | Inbound links from | Outbound links to |
|---|---|---|---|---|
| `airtable` | Phase 2 | `/alternatives/airtable` | TBD | homepage, pricing, MCP docs, Dataset API |
| `google-sheets` | Phase 3 | `/alternatives/google-sheets` | TBD | homepage, pricing, use cases, Dataset API |
| `baserow` | Phase 4 | `/alternatives/baserow` | TBD | homepage, MCP docs, Dataset API |
| `nocodb` | Phase 5 | `/alternatives/nocodb` | TBD | homepage, MCP docs, Dataset API |

### `/use-cases/[slug]` or future `/for/[slug]`

| Slug | Ships in phase | URL | Inbound links from | Outbound links to |
|---|---|---|---|---|
| `ai-agent-crm` | existing/Phase 1 expansion | `/use-cases/personal-crm` | homepage, use-cases index | Dataset API, MCP docs, Agent access |
| `agent-task-board` | existing/Phase 1 expansion | `/use-cases/agent-task-board` | homepage, use-cases index | Dataset API, MCP docs, projects docs |
| `feedback-triage` | existing/Phase 1 expansion | `/use-cases/feedback-triage` | homepage, use-cases index | public previews, Dataset API |

### `/compare/[slug]`

| Slug | Ships in phase | URL | Inbound links from | Outbound links to |
|---|---|---|---|---|
| `rowset-vs-airtable` | Phase 6 | `/compare/rowset-vs-airtable` | TBD | `/alternatives/airtable`, pricing, MCP docs |
| `rowset-vs-google-sheets` | Phase 7 | `/compare/rowset-vs-google-sheets` | TBD | `/alternatives/google-sheets`, pricing, Dataset API |

### `/playbooks/[slug]`

| Slug | Ships in phase | URL | Inbound links from | Outbound links to |
|---|---|---|---|---|
| `connect-ai-agent-to-dataset-api` | Phase 8 | `/playbooks/connect-ai-agent-to-dataset-api` | TBD | MCP docs, Dataset API, Agent access |
| `agent-managed-feedback-board` | Phase 9 | `/playbooks/agent-managed-feedback-board` | TBD | feedback use case, public previews, Dataset API |

## Anchor-text variations

- Rowset private dataset backend
- MCP dataset backend
- REST dataset API
- hosted MCP access
- Rowset Dataset API
- API-backed datasets
- agent-managed personal CRM
- agent task board
- feedback triage workflow
- public read-only previews
