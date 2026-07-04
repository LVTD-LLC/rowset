# Rowset SEO Sprint - Roadmap

> **Canonical document.** This file is the source of truth for the multi-phase Rowset SEO sprint. Every worktree/agent picking up SEO work on this project reads this file first.

## Mode

This initialize run was refreshed on 2026-07-04 from latest `origin/main` (`2d9389b`) in **manual research mode**. GSC, Ahrefs, and working DataForSEO credentials were not available from the repo shell, so volume, difficulty, traffic potential, and conversion values are estimates or validation prompts. Re-run with GSC, Ahrefs, DataForSEO, Semrush, Google Keyword Planner, Plausible API, or PostHog API before investing deeply in competitive pages.

## How to Use This Document

1. Read this entire `docs/seo-sprint.md` file.
2. Read `.seo/brand.md`, `.seo/link-inventory.md`, `.seo/keyword-research.json`, and `.seo/config.json`.
3. Find the next `pending` row in the Phase Status Tracker.
4. Execute one phase per PR.
5. In the same PR, update this tracker row to `completed` and update `.seo/link-inventory.md` when a new page ships.

Do not modify Reference Data, Conventions, Keyword Research Appendix, or phase ordering without an explicit product/SEO decision.

## Phase Status Tracker

| # | Phase | Pattern | Status | PR |
|---|---|---|---|---|
| 0 | Technical foundations: robots, sitemap headers, schema helpers | Setup | pending | - |
| 1 | Strengthen existing use-case pages as the internal-link spine | Use-case | pending | - |
| 2 | Ship `/alternatives/airtable` with an AI-agent dataset angle | Alternatives | pending | - |
| 3 | Ship `/alternatives/google-sheets` with an MCP/REST backend angle | Alternatives | pending | - |
| 4 | Ship `/alternatives/baserow` with honest open-source/no-code positioning | Alternatives | pending | - |
| 5 | Ship `/alternatives/nocodb` with SQL UI vs agent backend positioning | Alternatives | pending | - |
| 6 | Ship `/compare/rowset-vs-airtable` | Compare | pending | - |
| 7 | Ship `/compare/rowset-vs-google-sheets` | Compare | pending | - |
| 8 | Ship `/playbooks/connect-ai-agent-to-dataset-api` | Playbook | pending | - |
| 9 | Ship `/playbooks/agent-managed-feedback-board` | Playbook | pending | - |
| 10 | Off-page starter submissions and backlink target list | Off-page | pending | - |

**Conventions:**
- `pending` -> `in_progress` when work starts -> `completed` in the PR that ships it.
- PR column should be `branch <name> (PR TBD)` during work and `#NNN` after PR creation.
- If a phase is abandoned, set status to `skipped` with a one-line reason.

## Reference Data

### Site Facts

- **Domain:** https://rowset.lvtd.dev
- **Keyword data source:** manual estimates until measured tools are connected.
- **Connected signal sources:** production site, repo, web search, and live HTTP checks. Plausible/PostHog scripts are present on production, but API access was not available in the repo shell.
- **GSC property:** not configured.
- **Ahrefs project_id:** not configured.
- **Plausible site_id:** `rowset.lvtd.dev` inferred from script tag.
- **PostHog project_id:** not configured in repo shell.
- **Domain Rating:** unknown in manual mode.
- **Stack:** Django 6, Django templates, HTMX, Alpine.js, Tailwind/PostCSS.
- **Marketing pages root:** `apps/pages`, `frontend/templates/pages`.
- **Docs content root:** `apps/docs/content`.
- **Sitemap generator:** `rowset/sitemaps.py`.
- **Brand accent color:** emerald over slate/white surfaces.
- **Fonts:** Inter / system sans.

### Tool Availability Snapshot

| Source | Status | Used for | Config saved |
|---|---|---|---|
| GSC | missing | owned queries + indexing | `gsc_property: null` |
| Ahrefs | missing | DR, KD, volume, SERP, backlinks | `ahrefs_project_id: null` |
| DataForSEO | unavailable/unauthorized from shell | KD, volume, SERP | note in `.seo/config.json` |
| Plausible | detected on production, API not configured | conversion weighting later | `plausible_site_id: rowset.lvtd.dev` |
| PostHog | detected on production, API not configured | funnel/event weighting later | `posthog_project_id: null` |
| Web search | available | discovery | none |
| Web fetch/live HTTP | available | production verification | none |

### Existing Programmatic Surface

| Surface | URL pattern | Implementation |
|---|---|---|
| Use cases | `/use-cases/<slug>` | `apps/pages/use_cases.py`, `frontend/templates/pages/use-case-detail.html` |
| Docs | `/docs/<category>/<page>/` | `apps/docs/content`, docs views/templates |
| Blog | `/blog/<slug>` | `apps/blog`, Markdown-backed blog service/templates |
| Sitemap | `/sitemap.xml` | `rowset/sitemaps.py` |
| Public agent skill | `/SKILL.md` | core skill-serving path |
| Agent overview | `/llms.txt` | generated Rowset overview for agents/search tools |

### Critical Files

| File | What lives there |
|---|---|
| `PRODUCT.md` | Product/audience/positioning truth |
| `VISION.md` | Durable product direction and non-goals |
| `DESIGN.md` | Design system and visual rules |
| `apps/pages/use_cases.py` | Existing use-case page copy/data |
| `apps/pages/urls.py` | Marketing page routes |
| `frontend/templates/pages/landing-page.html` | Homepage copy and internal links |
| `frontend/templates/pages/pricing.html` | Pricing page copy |
| `frontend/templates/pages/use-cases-index.html` | Use-case index |
| `frontend/templates/pages/use-case-detail.html` | Use-case page template |
| `frontend/templates/base_landing.html` | Shared public meta/schema fallback |
| `rowset/sitemaps.py` | Sitemap entries |
| `apps/docs/content/**` | Docs pages and keyword-focused metadata |

## Technical Audit Snapshot

Run date: 2026-07-04.

Command:

```text
uv run python /home/node/.openclaw/workspace/agent-control-plane-config/skills/seo-sprint/scripts/tech_audit.py --domain https://rowset.lvtd.dev
```

Findings:

- `sitemap.xml` returns `200` and includes homepage, use cases, pricing, docs, and blog URLs.
- Production `robots.txt` returns `404`. This is the main Phase 0 fix.
- `sitemap.xml` response includes `X-Robots-Tag: noindex, noodp, noarchive`; review whether this header is inherited globally and remove it from sitemap responses if so.
- Homepage returns `200`, has a title, meta description, canonical, one H1, and JSON-LD.
- `/pricing` returns `200`; `/pricing/` returns the app 404 page. Decide whether to add slash redirects/canonical handling for common marketing routes.
- Sitemap-listed docs and use-case pages spot-check as indexable pages with titles/descriptions.

## Conventions

**URL slugs:** lowercase, hyphenated, never underscored.

**Honesty section:** every `/alternatives/*` page must include 3-4 honest tradeoffs where the competitor is better. This is non-negotiable.

**Positioning:** Rowset is not a spreadsheet replacement, no-code app builder, BI platform, or Google Sheets sync product. Keep the angle on private MCP/REST datasets for trusted agents.

**Internal-link minimums:**
- `/alternatives/*` -> at least 2 sibling alternatives, 1 feature/doc page, 1 pricing/signup link.
- `/use-cases/*` -> at least 2 feature/doc links and 1 sibling use case.
- `/compare/*` -> both related alternatives pages, pricing, and one setup/doc link.
- `/playbooks/*` -> at least 3 docs/features, 2 use cases, 1 alternative/comparison where relevant.
- Every new SEO page should be reachable from at least 2 existing pages.

**Word counts:**
- `/alternatives/*`: at least 600 words.
- `/compare/*`: at least 700 words.
- `/playbooks/*`: at least 2,500 words.
- Existing use-case pages should be expanded only where it improves concrete workflow usefulness.

**Schema:**
- Homepage: `SoftwareApplication` or `Product`, plus `Organization` when helper exists.
- Alternatives/use-cases/compare pages: `BreadcrumbList` and `FAQPage` where an FAQ section exists.
- Playbooks/blog posts: `Article` and `BreadcrumbList`.

## Keyword Research Appendix

All values are manual estimates. See `.seo/keyword-research.json` for machine-readable detail.

### A.1 - `/alternatives/[brand]` Candidates

| Keyword | Page | Est. volume | Est. difficulty | Confidence | Notes |
|---|---|---:|---|---|---|
| airtable alternatives | `/alternatives/airtable` | 1000+ | high | high | Broad SERP; Rowset must narrow to AI-agent-managed datasets. Airtable now also positions around data, workflows, and agents, so the page needs a clear "agent backend vs work platform" distinction. |
| google sheets alternatives | `/alternatives/google-sheets` | 1000+ | high | high | Broad SERP; target users who need MCP/REST and private agent workflows. |
| baserow alternatives | `/alternatives/baserow` | 100-500 | medium | medium | Strong open-source/no-code database adjacency. |
| nocodb alternatives | `/alternatives/nocodb` | 100-500 | medium | medium | Good comparison angle: SQL UI vs agent backend. |

### A.2 - Existing Use-Case Candidates

| Keyword | Existing URL | Est. volume | Est. difficulty | Confidence |
|---|---|---:|---|---|
| ai agent crm | `/use-cases/personal-crm` | 30-200 | medium | estimated |
| agent task board | `/use-cases/agent-task-board` | 30-200 | low-medium | estimated |
| feedback triage ai agent | `/use-cases/feedback-triage` | 10-100 | low | estimated |
| mcp dataset api | `/docs/features/mcp/` | 30-200 | low-medium | estimated |
| dataset api for ai agents | `/docs/api-reference/datasets/` | 30-200 | low-medium | estimated |

### A.3 - Compare Candidates

| Keyword | Page | Est. volume | Est. difficulty | Confidence | Notes |
|---|---|---:|---|---|---|
| rowset vs airtable | `/compare/rowset-vs-airtable` | 0-30 now | low | estimated | Branded capture for later; useful sales asset. |
| rowset vs google sheets | `/compare/rowset-vs-google-sheets` | 0-30 now | low | estimated | Useful decision page for setup conversations. |
| airtable vs baserow | `/compare/airtable-vs-baserow` | 100-500 | medium-high | medium | High intent, but third-party commentary unless Rowset is clearly included as a different category. |

### A.4 - Playbook Candidates

| Keyword | Page | Est. volume | Est. difficulty | Confidence |
|---|---|---:|---|---|
| connect ai agent to dataset api | `/playbooks/connect-ai-agent-to-dataset-api` | 30-200 | low-medium | estimated |
| mcp server for database | `/playbooks/mcp-server-for-database` | 100-500 | medium | estimated |
| agent managed feedback board | `/playbooks/agent-managed-feedback-board` | 10-100 | low | estimated |

### A.5 - Striking Distance

Not available in manual mode. Add Google Search Console queries ranking positions 5-20 when GSC access is available.

### A.6 - Conversion-Weighted Opportunities

Not available yet. Plausible and PostHog are present on the production site, but API IDs/access were not available from the repo shell. When connected, bias toward pages that lead to signup, agent API key creation, prompt copy, dataset creation, or Pro checkout.

### A.7 - Already-Saturated Head Terms to Avoid

- `database` - too broad and too competitive.
- `spreadsheet` - too broad and product positioning drift.
- `airtable alternative` - viable, but validate before targeting the singular variant; plural alternatives pages often capture broader demand.

## Phases

### Phase 0 - Technical Foundations

**Why:** Google needs a clean crawl path before new content matters.

**Scope:**

1. Add a production `robots.txt` route or static file that allows crawling and references `https://rowset.lvtd.dev/sitemap.xml`.
2. Confirm `robots.txt` returns 200 on production after deploy.
3. Review why `sitemap.xml` is served with `X-Robots-Tag: noindex, noodp, noarchive`; remove inherited `noindex` header from sitemap responses if it is globally configured.
4. Decide whether common marketing trailing-slash variants such as `/pricing/` should redirect to canonical no-slash routes instead of rendering a 404.
5. Add or centralize schema helpers for `SoftwareApplication`, `Organization`, `BreadcrumbList`, `FAQPage`, and `Article` if page-generating phases would otherwise duplicate JSON-LD.
6. Add `Organization` schema to the homepage if the helper exists.
7. Submit sitemap in Google Search Console and Bing Webmaster Tools.

**Files likely modified:**

- `apps/pages/urls.py` or a static file location for `robots.txt`
- `frontend/templates/base_landing.html` or a schema helper module/template
- `rowset/settings.py` only if headers need targeted sitemap handling
- `rowset/sitemaps.py` only if sitemap entries need adjustment

**Verification:**

```text
uv run python /home/node/.openclaw/workspace/agent-control-plane-config/skills/seo-sprint/scripts/tech_audit.py --domain https://rowset.lvtd.dev
curl -sI https://rowset.lvtd.dev/robots.txt
curl -s https://rowset.lvtd.dev/robots.txt
curl -sI https://rowset.lvtd.dev/sitemap.xml
```

### Phase 1 - Strengthen Existing Use-Case Pages as the Internal-Link Spine

**Why:** Rowset already has use-case pages; improve them before adding isolated programmatic pages.

**Scope:**

1. Add stronger internal links from homepage/use-case index into the most commercially useful pages.
2. Add links from each use-case page to MCP docs, Dataset API, pricing/signup, and 1-2 sibling use cases.
3. Consider adding concise FAQ sections to the use-case template and `FAQPage` JSON-LD where the questions are real.
4. Preserve product guardrails: public previews are read-only; MCP/REST remain the private paths.

**Verification:** page source has canonical, one H1, JSON-LD, and at least 3 relevant internal links per use-case page.

### Phase 2 - Ship `/alternatives/airtable`

**Why:** `airtable alternatives` is the largest obvious alternatives market. Rowset should target the specific sub-intent: "I need agents to maintain structured rows through an API/MCP backend."

**Required sections:**

- Best Airtable alternatives for AI-agent-managed datasets in 2026.
- When Airtable is still the better choice.
- Why Rowset is different: MCP-first, private by default, row/index/schema semantics, setup prompt.
- Migration decision table.
- FAQ.

**Quality gate:** at least 600 words, honesty section, FAQ schema, links to pricing, MCP docs, Dataset API, and at least 2 sibling alternatives once available.

### Phase 3 - Ship `/alternatives/google-sheets`

**Why:** many users start with Sheets for agent-managed lists, then hit authentication, schema, row lookup, and automation reliability limits.

**Angle:** not "Sheets is bad"; Rowset is for private agent workflows where MCP/REST, stable keys, and ownership boundaries matter.

**Quality gate:** at least 600 words, honesty section, FAQ schema, links to use cases and Dataset API.

### Phase 4 - Ship `/alternatives/baserow`

**Why:** Baserow owns "open-source Airtable alternative" positioning. Rowset should explain the narrower agent-native backend angle.

**Angle:** Baserow is stronger for no-code database UI and self-hosted app building; Rowset is stronger for trusted agents managing private datasets through MCP/REST.

**Quality gate:** at least 600 words, honesty section, FAQ schema, current Baserow feature/pricing review before writing.

### Phase 5 - Ship `/alternatives/nocodb`

**Why:** NocoDB appears in open-source no-code database comparisons and has a clear contrast with Rowset.

**Angle:** NocoDB is for exposing SQL databases through a spreadsheet-like UI; Rowset is for agent-owned structured datasets with MCP/REST access.

**Quality gate:** at least 600 words, honesty section, FAQ schema, current NocoDB feature/pricing review before writing.

### Phase 6 - Ship `/compare/rowset-vs-airtable`

**Why:** low-volume branded capture and a useful sales/decision page.

**Scope:** compare Rowset against Airtable for users deciding where trusted agents should keep structured work. Include "choose Airtable if" and "choose Rowset if" sections.

**Quality gate:** at least 700 words, comparison table, links to Airtable alternatives page, pricing, MCP docs, and Dataset API.

### Phase 7 - Ship `/compare/rowset-vs-google-sheets`

**Why:** users understand Sheets; this page frames when a spreadsheet stops being enough for agent-run data work.

**Scope:** compare permissions, private API access, row identity, schema metadata, exports, public previews, and agent setup.

**Quality gate:** at least 700 words, comparison table, links to Google Sheets alternatives page, pricing, use cases, and Dataset API.

### Phase 8 - Ship `/playbooks/connect-ai-agent-to-dataset-api`

**Why:** this is the most product-native educational topic: concrete setup, clear payoff, and good internal links to docs.

**Scope:** long-form guide showing when to use Rowset, how to create an API key, how to configure MCP, how to verify with user info/capabilities, how to create a dataset, and how to avoid leaking keys.

**Quality gate:** at least 2,500 words, code examples, Article schema, links to MCP docs, Dataset API, Agent access, and at least 2 use cases.

### Phase 9 - Ship `/playbooks/agent-managed-feedback-board`

**Why:** feedback triage is a concrete workflow with clear buyer pain and a strong demo path.

**Scope:** show how an agent turns scattered feedback into a structured dataset, dedupes themes, updates status, links customers, exports, and shares public previews when useful.

**Quality gate:** at least 2,500 words, concrete dataset schema, example rows, Article schema, links to feedback use case, public previews, Dataset API, and projects docs.

### Phase 10 - Off-Page Starter Submissions and Backlink Target List

**Why:** Rowset will need external signals before broad alternatives pages can rank.

**Scope:**

1. Create `.seo/backlink-targets.json`.
2. Research product directories, MCP directories, open-source/agent tool lists, and Airtable/Google Sheets alternative listicles.
3. Submit or prepare submissions where appropriate: Product Hunt, AlternativeTo, SaaSHub, Indie Hackers, Crunchbase, MCP directories.
4. Track status and target URL in the roadmap or backlink file.

**Quality gate:** each target has URL, contact/submission path, relevance, status, and next action.
