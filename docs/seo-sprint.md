# Rowset SEO Sprint - Roadmap

> **Canonical document.** This file is the source of truth for Rowset's multi-phase SEO sprint. Read it with `.seo/brand.md`, `.seo/keyword-research.json`, `.seo/link-inventory.md`, and `.seo/config.json` before starting a phase.

## Mode

Measured re-audit completed on 2026-07-15 from `origin/main` at `b93e5d6`. The refresh used direct Google Search Console, Plausible, PostHog, DataForSEO, Exa, Firecrawl, Jina Reader, production HTTP checks, and the current repository. Ahrefs is still not connected.

Technical recovery was rechecked on 2026-07-21 from `origin/main` at `377e1e9`. GSC now lists the submitted sitemap with zero errors or warnings. The live audit found exact canonicals and one H1 across all 54 sitemap URLs, repetitive title boilerplate, and 13 directly sampled historical routes still returning 404. Phase 5 repairs those remaining repository issues and adds broader regression coverage.

The plan changed materially since the July 4 initialization:

1. The docs and use-case information architecture moved, leaving 17 URLs in the SEO inventory returning 404.
2. GSC still has almost no visibility and lists no submitted sitemap for the Rowset property.
3. The strongest newly measured opportunity is the existing MCP database guide: `mcp database` has 480 US searches/month, KD 5, and $14.12 CPC.
4. The planned Dataset API guide has already shipped as `/blog/connect-ai-agent-to-dataset-api` in PR #244.
5. PostHog activation instrumentation now exists, but the 90-day sample is one person and cannot support conversion-weighted prioritization yet.

## How to Use This Document

1. Pick the lowest-numbered `pending` phase.
2. Execute one phase per PR unless the phase explicitly says it is an observation gate.
3. Re-research commercial claims and SERPs immediately before page work.
4. Update this tracker and `.seo/link-inventory.md` in the same PR.
5. Use canonical no-trailing-slash public URLs.

## Phase Status Tracker

| # | Phase | Pattern | Status | PR |
|---|---|---|---|---|
| 0 | Technical foundations: robots, sitemap headers, schema helpers | Setup | completed | #190 |
| 1 | Strengthen Dataset API, MCP docs, and use-case pages as the internal-link spine | Use-case/docs | completed | #193 |
| 2 | Ship the database MCP server guide | Playbook | completed | #196 |
| 3 | Ship `/blog/airtable-alternatives` | Blog alternatives | completed | #207 |
| 4 | Ship `/blog/google-sheets-alternatives` | Blog alternatives | completed | #209 |
| 5 | Repair SEO route drift, sitemap submission, canonicals, and title boilerplate | Technical refresh | completed | #341 |
| 6 | Ship `/blog/baserow-alternatives` | Blog alternatives | completed | #233 |
| 7 | Ship `/blog/nocodb-alternatives` | Blog alternatives | completed | #239 |
| 8 | Ship `/blog/connect-ai-agent-to-dataset-api` | Product guide | completed | #244 |
| 9 | Retarget `/docs/database-mcp-server` around the `mcp database` cluster | Existing-page boost | completed | #343 |
| 10 | Ship `/blog/spreadsheet-database-for-ai-agents` | Decision guide | completed | PR TBD |
| 11 | Build the off-page starter target list and submission backlog | Off-page | pending | - |
| 12 | Ship `/vs/airtable` when a sales/use-case trigger exists | Compare | completed | #277 |
| 13 | Review the fresh idempotency and agent-memory posts after 30 days of GSC data | Observation gate | pending | not before 2026-08-14 |
| 14 | Ship `/vs/google-sheets` as the next requested comparison | Compare | completed | #280 |

**Conventions:**

- `pending` -> `in_progress` when work starts -> `completed` in the shipping PR.
- During work, use `branch <name> (PR TBD)` in the PR column.
- Use `skipped` with a one-line reason when evidence invalidates a phase.
- Completed history stays in place even when later phases are reprioritized around it.

## Reference Data

### Site Facts

- **Domain:** https://rowset.lvtd.dev
- **GSC property:** `https://rowset.lvtd.dev/`
- **Plausible site:** `rowset.lvtd.dev`
- **PostHog project:** `493217` (`rowset`)
- **Authority baseline:** unknown/low; DataForSEO returned zero ranked-keyword rows and zero backlink-summary rows for the domain.
- **Stack:** Django 6, Django templates, HTMX, Alpine.js, Tailwind/PostCSS.
- **Content roots:** `apps/pages/content/docs`, `apps/pages/content/use-cases`, and `apps/pages/content/blog`.
- **Sitemap generator:** `rowset/sitemaps.py`.
- **Canonical public URL style:** no trailing slash, except the homepage.

### Tool Evidence Snapshot

| Source | Status | Credential/config discovery | API/tool call | Used for | Config saved | Reason |
|---|---|---|---|---|---|---|
| GSC | connected | Infisical `/services/google-search-console`; property from repo config | Search Analytics and sitemap-list calls succeeded | owned queries, pages, impressions, clicks, sitemap state | `gsc_property` | Sparse query baseline; sitemap submitted 2026-07-15 with zero errors or warnings when checked 2026-07-21 |
| Ahrefs | missing | loaded tools, runtime env, `TOOLS.md`, repo config, and Infisical checked | not attempted | DR, KD, SERP, backlinks | `ahrefs_project_id: null` | no credential/project available |
| DataForSEO | connected | Infisical `/services/dataforseo` | overview, suggestions, SERPs, ranked-keywords, and backlink calls succeeded | volume, KD, CPC, intent, SERP shape | US / English | measured the new MCP database cluster; domain calls returned zero rows |
| Plausible | connected | runtime credential and `TOOLS.md` host | pages, channels, sources, goals, and organic-page queries succeeded | traffic and landing pages | `plausible_site_id` | Organic Search now has 6 visitors; conversion goals remain absent |
| PostHog | connected | runtime credential and repo project ID | project lookup and 90-day HogQL query succeeded | product event availability | `posthog_project_id` | activation events exist but represent one person |
| Exa | connected | runtime credential | MCP database and agentic database searches succeeded | competitor/source discovery | none | surfaced current MCP database tools and agent-database products |
| Firecrawl | connected | runtime credential | RushDB extraction succeeded | competitor page extraction | none | verified current adjacent-product positioning |
| Jina Reader | connected | runtime credential | official MCP docs and Rowset route extraction succeeded | clean extraction and route verification | none | confirmed an outdated Rowset MCP URL returns 404 |
| Live HTTP | connected | direct production access | sitemap, robots, all 54 sitemap URLs, metadata, canonicals, H1s, and 13 sampled historical URLs checked | technical audit | none | canonicals and H1s pass; repetitive title boilerplate and 13 historical 404s remained before Phase 5 |

### Current Public Surfaces

| Surface | URL pattern | Implementation |
|---|---|---|
| Docs | `/docs/<slug>` | `apps/pages/content/docs` |
| Use cases | `/use-cases/<slug>` | `apps/pages/content/use-cases` |
| Blog | `/blog/<slug>` | `apps/pages/content/blog` |
| Public Markdown readers | `/docs/<slug>.md`, `/use-cases/<slug>.md`, `/blog/<slug>.md` | public Markdown renderer |
| Sitemap | `/sitemap.xml` | `rowset/sitemaps.py` |
| Public agent skill | `/SKILL.md` | public skill-serving path |
| Agent overview | `/llms.txt` | generated Rowset overview |

Retired `/tutorials/*`, `/how-to/*`, and most `/explanations/*` URLs must not be used as new internal-link targets. See `.seo/link-inventory.md` for replacements and redirect candidates.

## Technical Audit Snapshot

Run date: 2026-07-15.

- `/robots.txt` returns 200, allows crawling, and references the sitemap.
- `/sitemap.xml` returns 200, contains 46 URLs, and no longer inherits the old `X-Robots-Tag` header.
- All 46 sitemap URLs return 200 with unique titles and descriptions and one H1.
- Homepage schema includes `Organization` and `SoftwareApplication`.
- Homepage and pricing are missing canonical tags.
- Twelve titles crossed the audit's 60-character review heuristic; the longest cluster is the alternatives and technical blog posts. This is a review signal, not a hard Google limit.
- Seventeen of 36 absolute Rowset URLs in the prior link inventory return 404 because they use retired route families or obsolete trailing slashes.
- GSC's sitemap-list API returned zero submitted sitemaps.

### Technical Recovery Recheck

Run date: 2026-07-21.

- `/sitemap.xml` returns 200 and contains 54 canonical URLs.
- All 54 sitemap URLs return 200 with exact canonicals and one H1.
- Homepage and pricing canonicals are now present on current `main`.
- Fourteen rendered titles crossed the audit's review heuristic. Google does not define a character limit, so Phase 5 reduces redundant brand and section boilerplate while keeping each page's visible title as the single source of truth.
- Thirteen sampled historical `/tutorials/*`, `/how-to/*`, and `/explanations/*` URLs still return 404 in production; git history identifies 48 exact historical routes worth preserving.
- GSC lists `https://rowset.lvtd.dev/sitemap.xml`, submitted 2026-07-15, with `pending=false`, zero errors, and zero warnings.

## Keyword Research Appendix

Values are current DataForSEO US metrics from 2026-07-15 unless noted. Machine-readable evidence is in `.seo/keyword-research.json`.

### Owned Search and Analytics Baseline

- **GSC, last 90 days:** 8 impressions, 0 clicks, 3 query/page rows. `rowset` produced 6 impressions at average position 24.83. No meaningful striking-distance row exists.
- **Plausible, last 90 days:** 6 Organic Search visitors and 10 pageviews. Organic landing pages were `/` (6 visitors), `/blog`, `/docs/dataset-api`, and `/blog/baserow-alternatives` (1 visitor each).
- **Plausible goals:** only `Outbound Link: Click` (5 visitors, 9 events); no signup, trial, activation, checkout, or subscription goal.
- **PostHog, last 90 days:** dataset mutation, user-info, and dataset-created events now exist, but all belong to one person and have no landing-page attribution.
- **Implication:** use DataForSEO to order near-term work, while prioritizing crawl/indexation recovery and better conversion instrumentation.

### Highest-Value Clusters

| Keyword | Existing/target page | US volume | KD | CPC | Decision |
|---|---|---:|---:|---:|---|
| `mcp database` / `database mcp` | `/docs/database-mcp-server` | 480 | 5 | $14.12 | Highest priority after technical recovery; refresh existing page and inbound links |
| `dataset api` | `/docs/dataset-api` | 480 | 43 | $23.12 | Keep strengthening docs; too hard/ambiguous for a new broad page |
| `idempotent api` | `/blog/idempotent-ai-agent-updates` | 260 | 25 | n/a | Freshly shipped; observe for 30 days before changing |
| `ai agent memory` | `/blog/ai-agent-memory-vs-state` | 210 | 27 | $9.77 | Freshly shipped; observe for 30 days before changing |
| `spreadsheet database` | `/blog/spreadsheet-database-for-ai-agents` | 170 | 22 | $14.12 | Viable decision guide after the MCP refresh |
| `agentic database` | research later | 70 | 10 | $18.06 | Promising metric, but SERP intent is broad and authority-heavy |
| `ai agent crm` | `/use-cases/personal-crm` | 30 | 3 | $26.41 | Useful existing-page refinement, not a separate page |

The earlier spreadsheet-database CPC ($55.70) and database-MCP volume (70) are stale. Current measured values are $14.12 and 50 respectively; the larger opportunity is the `mcp database`/`database mcp` head cluster at 480.

### Alternatives Pages Already Shipped

| Keyword | Page | US volume | KD | CPC |
|---|---|---:|---:|---:|
| `airtable alternatives` | `/blog/airtable-alternatives` | 720 | 0 | $14.29 |
| `google sheets alternatives` | `/blog/google-sheets-alternatives` | 480 | 0 | $16.63 |
| `baserow alternatives` | `/blog/baserow-alternatives` | 70 | 0 | $8.08 |
| `nocodb alternatives` | `/blog/nocodb-alternatives` | 50 | 14 | $7.02 |

### SERP Reality

- `mcp database`: official MCP docs, Google Cloud, Oracle, an MCP directory, Medium, PyPI, and Reddit. Mixed authority plus user-generated/package results makes an existing-page boost plausible.
- `spreadsheet database`: Grist, Baserow, Airtable, Google Sheets, Zoho, educational sites, and Reddit. The intent is mixed product/education, so the Rowset page must be an honest decision guide.
- `agentic database`: AWS, Cockroach Labs, IBM, TileDB, and publishers dominate. Keep this as research until Rowset can own a narrower operational-state angle.

### Deferred or Gated

- `rowset vs airtable`: no measured row; build only for a real sales/user decision, not projected traffic.
- `rowset vs google sheets`: no measured row; treat the requested page as a reusable sales and agent-decision surface, not projected traffic.
- `airtable vs google sheets`: 260 searches/month, but Rowset is not a named side.
- `dataset api`: strong volume and CPC but KD 43 and ambiguous intent.
- Fresh idempotency and agent-memory posts: do not rewrite before 30 days of GSC data.

## Quality Conventions

- Use lowercase, hyphenated, canonical no-trailing-slash URLs.
- Every new page needs at least two real inbound internal links in the same PR.
- Alternative/comparison pages require an honest `choose the competitor if` section.
- Blog/explanation pages require current source links and the renderer's `BlogPosting`/`Article` schema.
- Comparison pages require a comparison table, clear decision criteria, and links to pricing, MCP docs, and Dataset API docs.
- Avoid implying that Rowset is a spreadsheet replacement, arbitrary SQL MCP proxy, BI platform, or no-code app builder.

## Phases

### Phase 5 - Repair Route Drift, Sitemap State, Canonicals, and Title Boilerplate

**Why now:** crawl/indexation is the bottleneck. The July 15 audit found route drift, missing canonicals, repetitive title boilerplate, and no sitemap listing. Current `main` fixed the canonicals and GSC now lists a healthy sitemap, but historical routes and the boilerplate still need repair.

**Scope:**

1. Replace stale internal references to retired `/how-to/*`, `/tutorials/*`, and `/explanations/*` routes with the canonical `/docs/*` and `/use-cases/*` URLs.
2. Add permanent redirects for retired public routes that may have external links or historical crawl signals, including the old database MCP server route.
3. Add canonical tags to the homepage and pricing page.
4. Reduce redundant title boilerplate without creating separate search-only titles or changing editorial H1s.
5. Submit or verify `https://rowset.lvtd.dev/sitemap.xml` in GSC; if API submission cannot be authorized, document the exact manual step and verification date.
6. Add a deterministic test/audit that fails when canonical inventory URLs return 404 or use the wrong slash form.

**Verification:** zero stale canonical internal-link targets, homepage/pricing canonicals match their URLs, every sitemap page has a descriptive title, and GSC shows the submitted sitemap.

**Completed 2026-07-21:** restored permanent redirects for 48 exact historical routes, normalized trailing-slash variants for current public pages, shortened repetitive title branding while retaining one authoritative page title, and added deterministic sitemap/inventory tests for 200 responses, slash form, exact canonicals, and title presence. GSC independently reports the submitted sitemap with zero errors or warnings.

### Phase 9 - Boost `/docs/database-mcp-server` for the MCP Database Cluster

**Why:** `mcp database` and `database mcp` each map to a 480-volume, KD 5, $14.12-CPC cluster. This is substantially stronger than the original `database mcp server` metric.

**Scope:**

1. Rework title, description, H1/H2s, and opening copy around the natural `MCP database` decision while preserving product accuracy.
2. Explain the boundary between a direct SQL/database MCP server and Rowset's hosted, agent-managed dataset model.
3. Cover `mcp for database`, `database mcp server`, connection safety, stable row identity, and when a direct database tool is better.
4. Add inbound links from `/docs/connect-mcp`, `/docs/dataset-api`, and `/blog/mcp-vs-rest-ai-agents`.
5. Re-run the live SERP and extract the top current official/product pages before drafting.

**Quality gate:** no keyword stuffing, at least three inbound links, current primary sources, honest direct-database-MCP tradeoffs, canonical/schema/sitemap checks green.

**Completed 2026-07-21:** refreshed the Google US SERP for `mcp database` and `database
mcp`, then retargeted the guide around the architecture decision. The page now includes a direct
definition, balanced comparison, three-question decision test, safety and stable-identity sections,
live-PAA FAQs with `FAQPage` schema, and current MCP, Google, and Microsoft primary sources. Added
inbound links from MCP setup, Dataset API, and MCP-vs-REST content.

### Phase 10 - Ship `/blog/spreadsheet-database-for-ai-agents`

**Why:** `spreadsheet database` has 170 US searches/month, KD 22, and $14.12 CPC. The opportunity is real but below the MCP cluster and carries positioning risk.

**Scope:** write a decision guide covering spreadsheet, spreadsheet-database, and agent-dataset-backend choices. Include `use a spreadsheet database if...` and `use Rowset if...` sections.

**Quality gate:** at least 1,800 useful words, current source links, `BlogPosting` schema, links from Google Sheets alternatives and agent-managed datasets, and links out to MCP/Dataset API/use-case pages.

**Completed 2026-07-22:** published a three-surface decision guide covering ordinary
spreadsheets, relational spreadsheet-databases, and agent dataset backends. The guide
adds a six-question agent handoff test for operator, identity, schema, relationships,
write access, and recovery; cites current Google Sheets, Airtable, Grist, and Rowset
primary sources; and adds inbound links from the Google Sheets alternatives and
agent-managed dataset guides.

### Phase 11 - Off-Page Starter Target List

**Why:** DataForSEO returned no ranked-keyword or backlink baseline for the domain. Content alone is unlikely to move broader alternatives terms.

**Scope:** create `.seo/backlink-targets.json` with MCP directories, open-source/agent tool lists, database-MCP roundups, relevant product directories, and pages already linking to adjacent tools. Research and prepare submissions; do not send outreach or publish submissions without the required approval.

**Quality gate:** every target has a source URL, relevance, target Rowset page, submission/contact path, status, and next action.

### Phase 12 - Rowset vs Airtable, Triggered by Use Rather Than Volume

**Why:** no measured demand exists for `rowset vs airtable`. This page is sales enablement, not a current traffic bet.

**Trigger:** Rasul requested the comparison page as the first entry in a reusable `/vs/` series on 2026-07-15.

**Quality gate:** at least 900 useful words, current Airtable product/pricing sources, comparison table, strong honesty section, and internal links from the Airtable alternatives page and pricing.

### Phase 13 - Thirty-Day Observation Gate

**Not before:** 2026-08-14.

Review GSC query/page data for `/blog/idempotent-ai-agent-updates` and `/blog/ai-agent-memory-vs-state`. Only schedule refreshes if impressions show a clear query/title mismatch, position 5-20 creates a striking-distance opportunity, or indexing/canonical issues appear.

### Phase 14 - Rowset vs Google Sheets, Requested Comparison

**Why:** no measured direct-query demand exists for `rowset vs google sheets`,
but Rasul selected Google Sheets as the next page in the reusable `/vs/` series
on 2026-07-15. This is a product-decision and sales-enablement page.

**Quality gate:** at least 1,200 useful words, current primary Google sources,
comparison table, strong `choose Google Sheets if` section, AI SEO and
product-led SEO review, and inbound links from the shared footer, Google Sheets
alternatives page, and agent-managed datasets guide.
