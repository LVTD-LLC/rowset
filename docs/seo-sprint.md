# Rowset SEO Sprint - Roadmap

> **Canonical document.** This file is the source of truth for the multi-phase Rowset SEO sprint. Every worktree/agent picking up SEO work on this project reads this file first.

## Mode

This initialize run was refreshed on 2026-07-04 from latest `origin/main` (`2d9389b`), then re-run with connected measurement tools after PR review feedback. This roadmap now uses Google Search Console, Plausible, PostHog, DataForSEO, Exa, Firecrawl, Jina Reader, and live HTTP checks where available. Ahrefs is still not connected.

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
| 1 | Strengthen Dataset API, MCP docs, and use-case pages as the internal-link spine | Use-case/docs | pending | - |
| 2 | Ship `/playbooks/database-mcp-server` from measured MCP/database demand | Playbook | pending | - |
| 3 | Ship `/alternatives/airtable` with an AI-agent dataset angle | Alternatives | pending | - |
| 4 | Ship `/alternatives/google-sheets` with an MCP/REST backend angle | Alternatives | pending | - |
| 5 | Ship `/playbooks/spreadsheet-database-for-ai-agents` | Playbook | pending | - |
| 6 | Ship `/alternatives/baserow` with honest open-source/no-code positioning | Alternatives | pending | - |
| 7 | Ship `/alternatives/nocodb` with SQL UI vs agent backend positioning | Alternatives | pending | - |
| 8 | Ship `/playbooks/connect-ai-agent-to-dataset-api` as a strategic product-native guide | Playbook | pending | - |
| 9 | Ship `/compare/rowset-vs-airtable` after alternatives pages exist | Compare | pending | - |
| 10 | Off-page starter submissions and backlink target list | Off-page | pending | - |

**Conventions:**
- `pending` -> `in_progress` when work starts -> `completed` in the PR that ships it.
- PR column should be `branch <name> (PR TBD)` during work and `#NNN` after PR creation.
- If a phase is abandoned, set status to `skipped` with a one-line reason.

## Reference Data

### Site Facts

- **Domain:** https://rowset.lvtd.dev
- **Keyword data source:** DataForSEO measured US keyword volume, KD, CPC, SERP, and backlink-strength signals; GSC/Plausible/PostHog for owned baseline.
- **Connected signal sources:** GSC, Plausible, PostHog, DataForSEO, Exa, Firecrawl, Jina Reader, live HTTP checks, production site, and repo.
- **GSC property:** `https://rowset.lvtd.dev/`.
- **Ahrefs project_id:** not configured.
- **Plausible site_id:** `rowset.lvtd.dev`.
- **PostHog project_id:** `493217` (`rowset`).
- **Domain Rating:** unknown; use DataForSEO KD/backlink signals until Ahrefs is connected.
- **Stack:** Django 6, Django templates, HTMX, Alpine.js, Tailwind/PostCSS.
- **Marketing pages root:** `apps/pages`, `frontend/templates/pages`.
- **Docs content root:** `apps/docs/content`.
- **Sitemap generator:** `rowset/sitemaps.py`.
- **Brand accent color:** emerald over slate/white surfaces.
- **Fonts:** Inter / system sans.

### Tool Availability Snapshot

| Source | Status | Used for | Config saved |
|---|---|---|---|
| GSC | connected | owned queries + indexing | `gsc_property: https://rowset.lvtd.dev/` |
| Ahrefs | missing | DR, KD, volume, SERP, backlinks | `ahrefs_project_id: null` |
| DataForSEO | connected | US volume, KD, CPC, SERP, backlink strength | `dataforseo_location: United States`, `dataforseo_language: English` |
| Plausible | connected | landing pages, channels, goals | `plausible_site_id: rowset.lvtd.dev` |
| PostHog | connected | product events/funnel availability | `posthog_project_id: 493217` |
| Exa | connected | competitor and adjacent-tool discovery | none |
| Firecrawl | connected | competitor page extraction | none |
| Jina Reader | connected | competitor/listicle extraction | none |
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

Values below are measured unless explicitly labeled otherwise. See `.seo/keyword-research.json` for machine-readable detail.

### Owned Search and Analytics Baseline

- **GSC, last 90 days:** one query/page row: `rowset` -> homepage, 1 impression, 0 clicks, average position 9. There are no meaningful striking-distance opportunities yet.
- **Plausible, last 90 days:** 42 direct visitors, 7 referral visitors, 2 organic-social visitors, and no Organic Search rows. Top public pages include `/` (34 visitors), `/home` (15), `/docs/getting-started/introduction/` (9), `/use-cases` (7), `/docs/features/mcp/` (4), and `/accounts/signup/` (4).
- **Plausible goals:** one `Outbound Link: Click`; no signup/activation goal data available.
- **PostHog, last 90 days:** project `rowset` is connected, but only `$set` (220) and `$identify` (2) events were present. No pageview, signup, dataset, project, checkout, or subscription events were available for conversion weighting.
- **Implication:** market demand should come from DataForSEO for now, but Phase 0/1 should improve crawlability, internal links, and measurement before relying on conversion-weighted SEO decisions.

### A.1 - `/alternatives/[brand]` Candidates

| Keyword | Page | US volume | KD | CPC | Notes |
|---|---|---:|---|---|---|
| airtable alternatives | `/alternatives/airtable` | 720 | 0 | $15.50 | Commercial intent. SERP is broad/listicle-heavy; Rowset needs a narrow "AI-agent dataset backend" angle. |
| google sheets alternatives | `/alternatives/google-sheets` | 480 | 0 | $16.63 | Broad informational intent. Target the subset that needs MCP/REST, private keys, and stable row identity. |
| baserow alternatives | `/alternatives/baserow` | 70 | 0 | $5.41 | Smaller but relevant open-source/no-code database adjacency. |
| nocodb alternatives | `/alternatives/nocodb` | 50 | 14 | $5.61 | Smaller and harder; useful after the first alternatives pages. |
| grist alternatives | deferred | 10 | n/a | n/a | Too small for an early standalone page. |

### A.2 - Existing Use-Case Candidates

| Keyword | Existing URL / Target | US volume | KD | CPC |
|---|---|---:|---|---|
| dataset api | `/docs/api-reference/datasets/` | 480 | 43 | $24.07 |
| spreadsheet database | `/playbooks/spreadsheet-database-for-ai-agents` | 170 | 20 | $55.70 |
| database mcp server | `/playbooks/database-mcp-server` | 70 | 16 | $14.92 |
| mcp server for database | `/playbooks/database-mcp-server` | 20 | 16 | n/a |
| ai agent crm | `/use-cases/personal-crm` | 30 | 3 | $22.77 |
| agent task board | `/use-cases/agent-task-board` | no measured row | n/a | n/a |
| feedback triage ai agent | `/use-cases/feedback-triage` | no measured row | n/a | n/a |

### A.3 - Compare Candidates

| Keyword | Page | US volume | KD | CPC | Notes |
|---|---|---:|---|---|---|
| airtable vs google sheets | deferred research input | 320 | 0 | $7.75 | Good demand, but Rowset is not one of the compared brands; use for positioning research, not an early page. |
| airtable vs baserow | deferred research input | 20 | 0 | $2.95 | Low measured volume and third-party framing. |
| rowset vs airtable | `/compare/rowset-vs-airtable` | no measured row | n/a | n/a | Useful later as sales enablement after alternatives pages exist. |

### A.4 - Playbook Candidates

| Keyword | Page | US volume | KD | Notes |
|---|---|---:|---|---|
| database mcp server | `/playbooks/database-mcp-server` | 70 | 16 | Measured query variant from DataForSEO suggestions. |
| connect ai agent to dataset api | `/playbooks/connect-ai-agent-to-dataset-api` | no measured row | n/a | Still strategic/product-native, but not a demand-led first page. |
| agent managed feedback board | `/playbooks/agent-managed-feedback-board` | no measured row | n/a | Keep later unless product/content strategy overrides search demand. |

### A.5 - Striking Distance

No meaningful opportunities yet. GSC has one Rowset impression in the last 90 days; the homepage averaged position 9 for `rowset`, but with only 1 impression and 0 clicks.

### A.6 - Conversion-Weighted Opportunities

Not available yet despite connected tools. Plausible has no Organic Search channel rows and no signup/activation goals; PostHog has no pageview or conversion events in the Rowset project. Add/verify signup, API-key creation, dataset creation, prompt-copy, checkout, and subscription events before using analytics to rank SEO pages by revenue value.

### A.7 - Already-Saturated Head Terms to Avoid

- `database` - too broad and too competitive.
- `spreadsheet` - too broad and product positioning drift.
- `dataset api` - attractive volume/CPC, but KD 43 with a backlink-heavy SERP; strengthen docs/internal links before chasing it directly.
- `airtable vs google sheets` - measured 320 searches/month, but Rowset is not a named side of the comparison.

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

### Phase 1 - Strengthen Dataset API, MCP Docs, and Use-Case Pages as the Internal-Link Spine

**Why:** DataForSEO shows real demand for `dataset api` (480 US searches/month, KD 43, $24.07 CPC), but the SERP is backlink-heavy. Rowset should strengthen the pages it already owns before adding isolated programmatic pages.

**Scope:**

1. Add stronger internal links from homepage/use-case index into Dataset API docs, MCP docs, and the most commercially useful use cases.
2. Add links from each use-case page to MCP docs, Dataset API, pricing/signup, and 1-2 sibling use cases.
3. Expand the Dataset API and MCP docs where they can clearly answer `dataset api`, `database mcp server`, and agent-setup questions.
4. Consider concise FAQ sections and `FAQPage` JSON-LD where questions are real and not keyword stuffing.
5. Preserve product guardrails: public previews are read-only; MCP/REST remain the private paths.

**Verification:** page source has canonical, one H1, JSON-LD, and at least 3 relevant internal links per use-case page.

### Phase 2 - Ship `/playbooks/database-mcp-server`

**Why:** `database mcp server` has measured demand (70 US searches/month, KD 16, $14.92 CPC), and Exa surfaced adjacent MCP/database tools. This is more concrete than the original unmeasured "connect agent to dataset API" seed.

**Scope:** explain when to use a hosted agent dataset backend instead of connecting an agent directly to a database, how Rowset's hosted MCP setup works, where a direct database MCP is better, and how to keep credentials/private data out of prompts.

**Quality gate:** at least 2,500 words, Article schema, code/setup examples, links to MCP docs, Dataset API, Agent access, pricing, and relevant use cases.

### Phase 3 - Ship `/alternatives/airtable`

**Why:** `airtable alternatives` has measured demand (720 US searches/month, KD 0, $15.50 CPC), but the SERP is broad and listicle-heavy. Rowset should target the specific sub-intent: "I need agents to maintain structured rows through an API/MCP backend."

**Required sections:**

- Best Airtable alternatives for AI-agent-managed datasets in 2026.
- When Airtable is still the better choice.
- Why Rowset is different: MCP-first, private by default, row/index/schema semantics, setup prompt.
- Migration decision table.
- FAQ.

**Quality gate:** at least 600 words, honesty section, FAQ schema, links to pricing, MCP docs, Dataset API, and at least 2 sibling alternatives once available.

### Phase 4 - Ship `/alternatives/google-sheets`

**Why:** `google sheets alternatives` has measured demand (480 US searches/month, KD 0, $16.63 CPC). Many users start with Sheets for agent-managed lists, then hit authentication, schema, row lookup, and automation reliability limits.

**Angle:** not "Sheets is bad"; Rowset is for private agent workflows where MCP/REST, stable keys, and ownership boundaries matter.

**Quality gate:** at least 600 words, honesty section, FAQ schema, links to use cases and Dataset API.

### Phase 5 - Ship `/playbooks/spreadsheet-database-for-ai-agents`

**Why:** `spreadsheet database` has measured demand (170 US searches/month, KD 20, $55.70 CPC). The CPC is strong, but this can become a positioning trap unless the page is explicit that Rowset is not a spreadsheet replacement.

**Scope:** show when a spreadsheet-database tool is the right answer, when an AI-agent dataset backend is the better fit, and how Rowset fits private MCP/REST workflows.

**Quality gate:** at least 2,500 words, Article schema, honest "use a spreadsheet database if..." section, links to Dataset API, MCP docs, Google Sheets alternatives, and relevant use cases.

### Phase 6 - Ship `/alternatives/baserow`

**Why:** `baserow alternatives` has measured demand (70 US searches/month, KD 0, $5.41 CPC). Baserow owns "open-source Airtable alternative" positioning; Rowset should explain the narrower agent-native backend angle.

**Angle:** Baserow is stronger for no-code database UI and self-hosted app building; Rowset is stronger for trusted agents managing private datasets through MCP/REST.

**Quality gate:** at least 600 words, honesty section, FAQ schema, current Baserow feature/pricing review before writing.

### Phase 7 - Ship `/alternatives/nocodb`

**Why:** `nocodb alternatives` has measured demand (50 US searches/month, KD 14, $5.61 CPC). NocoDB appears in open-source no-code database comparisons and has a clear contrast with Rowset.

**Angle:** NocoDB is for exposing SQL databases through a spreadsheet-like UI; Rowset is for agent-owned structured datasets with MCP/REST access.

**Quality gate:** at least 600 words, honesty section, FAQ schema, current NocoDB feature/pricing review before writing.

### Phase 8 - Ship `/playbooks/connect-ai-agent-to-dataset-api`

**Why:** exact-match demand was not measured, but this remains the most product-native educational topic: concrete setup, clear payoff, and good internal links to docs.

**Scope:** long-form guide showing when to use Rowset, how to create an API key, how to configure MCP, how to verify with user info/capabilities, how to create a dataset, and how to avoid leaking keys.

**Quality gate:** at least 2,500 words, code examples, Article schema, links to MCP docs, Dataset API, Agent access, and at least 2 use cases.

### Phase 9 - Ship `/compare/rowset-vs-airtable`

**Why:** no measured demand exists yet for `rowset vs airtable`, but it becomes useful sales enablement after `/alternatives/airtable` exists.

**Scope:** compare Rowset against Airtable for users deciding where trusted agents should keep structured work. Include "choose Airtable if" and "choose Rowset if" sections.

**Quality gate:** at least 700 words, comparison table, links to Airtable alternatives page, pricing, MCP docs, and Dataset API.

### Phase 10 - Off-Page Starter Submissions and Backlink Target List

**Why:** Rowset will need external signals before broad alternatives pages can rank.

**Scope:**

1. Create `.seo/backlink-targets.json`.
2. Research product directories, MCP directories, open-source/agent tool lists, and Airtable/Google Sheets alternative listicles.
3. Submit or prepare submissions where appropriate: Product Hunt, AlternativeTo, SaaSHub, Indie Hackers, Crunchbase, MCP directories.
4. Track status and target URL in the roadmap or backlink file.

**Quality gate:** each target has URL, contact/submission path, relevance, status, and next action.
