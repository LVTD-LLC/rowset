# SEO brief: share AI-agent data safely

## Selection

- **Title:** How to share AI-agent data safely
- **Slug:** `/blog/share-ai-agent-data-safely`
- **Primary keyword:** share AI agent data
- **Type:** security decision guide
- **Backlog decision:** highest-priority unshipped candidate (score 18). The measured `spreadsheet database` candidate scores lower and remains reserved for sprint phase 10.
- **Search data:** unmeasured for the exact query. No volume or difficulty is claimed.
- **Live SERP read (2026-07-16):** results are fragmented across agent-platform sharing docs, MCP authorization guidance, vendor security material, and community questions. The gap is a product-grounded decision guide that distinguishes private live agent access, point-in-time exports, and deliberately public read-only views.

## Product-led SEO check

- **User job:** share agent-managed rows with another agent, service, client, or reviewer without accidentally granting write access or publishing private working data.
- **Product surface:** scoped Rowset agent keys, hosted MCP, Dataset API, authenticated exports, optional read-only public previews, password protection, dataset instructions, archive behavior, and separate linked datasets.
- **Business job:** lead a security-conscious user into the agent access docs, public-preview docs, Dataset API, a concrete feedback-triage use case, and the hosted trial.
- **Credible angle:** Rowset has distinct private work, file handoff, and read-only sharing surfaces. The guide maps the decision to those current controls and documents their limits.
- **Moat:** the `audience -> action -> lifetime` contract is applied to current Rowset permissions, preview headers, export formats, and dataset design patterns rather than presented as generic AI-security advice.

## AI SEO / entity map

Must cover: AI agent data sharing; audience; least privilege; read versus write; bearer API keys; secret storage; MCP; REST; object-level authorization; public previews; password-protected sharing; exports; copies outside the source system; data minimization; separate review datasets; dataset instructions; access lifetime; revocation; preview cleanup; and archive behavior.

Questions to answer:

1. What is the safest way to share data with an AI agent?
2. Is a password-protected public preview private?
3. Should a user share a live dataset or export a file?
4. Can a public preview change Rowset rows?
5. When should a workflow create a separate dataset for sharing?

## Table stakes versus gap

Table stakes include least privilege, secret storage, permission checks, data minimization, and revocation. Search results discuss those ideas separately or inside one vendor's agent-sharing model. This piece adds a Rowset-specific choice among four concrete delivery paths and gives each path an explicit cleanup action.

## Information gain

The original element is the **audience -> action -> lifetime** sharing contract. It converts an ambiguous request to "share the dataset" into a repeatable selection among scoped MCP, scoped REST, authenticated export, and public preview. It also adds the share-safe dataset pattern: publish an allowlisted schema rather than exposing the private working schema.

## Claim ledger

| Claim | Source(s) | Tier / date | Verification |
|---|---|---|---|
| MCP authorization is recommended for servers that access user-specific data, and current MCP guidance recommends short-lived tokens, validation, HTTPS, narrow scopes, secure storage, and avoiding credential logs. | [MCP authorization guidance](https://modelcontextprotocol.io/docs/tutorials/security/authorization) | Primary protocol documentation, checked 2026-07-16 | Verified (primary) |
| APIs that receive an object ID should check whether the authenticated user may perform the requested action on that object. | [OWASP API1:2023 Broken Object Level Authorization](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/) | Primary security guidance, checked 2026-07-16 | Verified (primary) |
| Rowset agent keys support Read, Read + write, and Admin permission levels with distinct jobs. | `apps/pages/content/docs/configure-agent-access.md`; `apps/core/capabilities.py`; `apps/core/tests/test_agent_api_keys.py` | Primary Rowset docs/source/tests, 2026-07-16 | Verified |
| Rowset MCP and REST are private bearer-key paths; public previews are sharing paths rather than agent authentication. | `apps/pages/content/docs/mcp-rest-public-previews.md`; `apps/pages/content/docs/configure-agent-access.md` | Primary Rowset docs, 2026-07-16 | Verified |
| Rowset public browser and JSON access are read-only, can be password protected, and should be disabled after the sharing window. | `apps/pages/content/docs/share-public-previews.md`; `apps/api/views.py`; `apps/datasets/tests/test_public_previews.py` | Primary Rowset docs/source/tests, 2026-07-16 | Verified |
| Protected public API requests send the preview password in `X-Rowset-Public-Password`. | `apps/pages/content/docs/share-public-previews.md`; `apps/api/views.py`; `apps/datasets/public_previews.py` | Primary Rowset docs/source, 2026-07-16 | Verified |
| Rowset exports currently include CSV, JSONL, XLSX, and SQLite endpoints and require authenticated access. | `apps/pages/content/docs/archive-export-troubleshoot.md`; `apps/api/views.py`; `apps/datasets/tests/test_csv_datasets.py` | Primary Rowset docs/source/tests, 2026-07-16 | Verified |
| Archiving a Rowset dataset disables its public preview. | `apps/pages/content/docs/archive-export-troubleshoot.md`; `apps/api/services.py`; `apps/datasets/tests/test_public_previews.py` | Primary Rowset docs/source/tests, 2026-07-16 | Verified |

## Counter-evidence and limits

- A password reduces casual preview access but is still shared knowledge. It is not equivalent to account-scoped private MCP or REST authorization.
- Revoking a key or disabling a preview cannot revoke a file that was already exported and copied elsewhere.
- Dataset instructions guide an agent but do not enforce permissions. The article keeps instructions separate from actual authentication and authorization controls.
- The article does not claim that Rowset implements the OAuth 2.1 flow in the cited MCP guide. It cites the guide for general token-handling and least-privilege principles, while accurately describing Rowset's current bearer API-key model.

## Internal links

- `/docs/connect-mcp`
- `/docs/dataset-api`
- `/docs/configure-agent-access`
- `/docs/archive-export-troubleshoot`
- `/docs/share-public-previews`
- `/blog/relationship-modeling-agent-datasets`
- `/blog/structure-dataset-instructions-ai-agents`
- `/use-cases/feedback-triage`
- `/pricing`

Inbound links added from `/blog/agent-managed-datasets`, `/blog/connect-ai-agent-to-dataset-api`, and `/use-cases/feedback-triage`.

## AI SEO final checklist

- Direct answer and decision framework appear before the first H2.
- The selection table and checklist are independently extractable.
- Important external security claims use current primary sources.
- Product claims trace to current source, tests, or docs.
- Entity map and five concrete questions are covered.
- Freshness is visible through `published_at: 2026-07-16`.
- The existing renderer emits `BlogPosting` schema from frontmatter. The renderer does not currently emit `FAQPage`, so FAQ schema is considered but not invented in the content file.
