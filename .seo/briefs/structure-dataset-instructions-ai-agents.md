# SEO Brief: How to structure dataset instructions for AI agents

## Selection

- Date: 2026-07-07
- Type: how-to / product-native tutorial
- Slug: `/blog/structure-dataset-instructions-ai-agents`
- Target keyword: `AI agent dataset instructions`
- Volume/KD: unmeasured / n/a
- Source of priority: highest-priority unshipped candidate in `.seo/content-ledger.md`
- Exclusions checked: shipped blog posts, `.seo/content-ledger.md`, and `docs/seo-sprint.md`

## Product-led SEO check

- User job: builders and operators need a repeatable way to tell trusted AI agents how to use structured rows without restating rules in every chat.
- Product surface: Rowset dataset `instructions`, `metadata`, `column_types`, `index_column`, MCP `get_dataset`, REST Dataset API.
- Business job: supports Rowset's agent-native dataset positioning and links readers into MCP setup, Dataset API, schema design, and use-case pages.
- Moat: Rowset can write from the product behavior itself, not a generic prompt-engineering checklist.
- Avoided drift: does not position Rowset as a spreadsheet replacement, no-code platform, BI tool, or Google Sheets sync product.

## AI SEO / AEO check

- Direct answer appears in the first paragraph.
- Process structure: short rule, what belongs in instructions, what belongs in metadata, column descriptions, reusable template, examples, QA checklist, FAQ.
- Extractable claims:
  - Good dataset instructions tell an agent what rows mean, which actions are safe, and when to ask.
  - Put durable workflow rules in `instructions`, machine-readable rules in `metadata`, and field meaning in column descriptions.
  - Agents should call `get_dataset` before row mutations so they can inspect headers, schema, instructions, metadata, relationships, and the index column.
- Entity coverage: Rowset, MCP, REST, Dataset API, `get_dataset`, `instructions`, `metadata`, `column_types`, `index_column`, choice columns, structured outputs, schema descriptions.
- Schema: existing Rowset blog renderer emits `BlogPosting` JSON-LD with `datePublished`, `dateModified`, author, publisher, keywords, and article body.

## Claim Ledger

| Claim | Source | Tier | Verification |
|---|---|---|---|
| MCP tools expose names, descriptions, and input schemas so models can discover and invoke tools. | Model Context Protocol tools spec, 2025: https://modelcontextprotocol.io/specification/2025-03-26/server/tools | Primary | Lines 79-84 in live source; consistent with Rowset MCP docs and capabilities. |
| OpenAI Structured Outputs recommends clear key names/descriptions and strict schemas constrain unexpected extra keys. | OpenAI Structured Outputs guide, 2026: https://developers.openai.com/api/docs/guides/structured-outputs | Primary | Live source lines 4265-4269 and 6451-6455. |
| Anthropic recommends clear, explicit instructions and enough workflow context for Claude. | Anthropic prompting best practices, 2026: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices | Primary | Live source lines 197-201. |
| Rowset dataset creation accepts `instructions`, `metadata`, `index_column`, and `column_types`; Dataset API returns `column_schema`. | `apps/pages/content/docs/dataset-api.md` | Product primary | Checked in repo during this run. |
| Rowset MCP workflow recommends calling `get_dataset` before row operations and exposes dataset instructions/schema/metadata. | `apps/pages/content/docs/connect-mcp.md`; `apps/core/capabilities.py` | Product primary | Checked in repo during this run. |
| Rowset use-case pages provide concrete content pipeline, feedback triage, and inventory examples. | `apps/pages/content/use-cases/*.md` | Product primary | Checked in repo during this run. |

## Information Gain

The piece turns Rowset's product primitives into a concrete instruction architecture: instructions for durable human-readable operating rules, metadata for parseable rules, column descriptions for field meaning, and `get_dataset` before mutation. Existing Rowset docs mention these fields separately; this post gives operators reusable templates and examples for agent-managed datasets.

## Internal Links

- `/docs/connect-mcp/`
- `/docs/dataset-api/`
- `/docs/design-schema/`
- `/blog/choose-index-column-agent-rows`
- `/use-cases/content-pipeline/`
- `/use-cases/feedback-triage/`
- `/use-cases/product-inventory-catalog/`
- `/blog/mcp-vs-rest-ai-agents`

## QA Notes

- Human-first usefulness: practical templates and workflow examples.
- No fabricated metrics, quotes, customers, or screenshots.
- Freshness: published 2026-07-07; sources checked live on 2026-07-07.
- Forbidden words check: avoids "revolutionary", "seamless", "synergy", "unlock the power", "spreadsheet replacement", "no-code platform", and "AI magic".
