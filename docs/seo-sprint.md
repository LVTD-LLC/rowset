# Rowset SEO Sprint - Roadmap

> **Canonical document.** This file is the source of truth for the multi-phase Rowset SEO sprint. Every worktree/agent picking up SEO work on this project reads this file first.

## Mode

This initialize run was completed on 2026-07-03 in **manual research mode** because Ahrefs MCP was not available in the session. Volume, difficulty, and traffic potential values below are estimates or validation prompts. Re-run with Ahrefs, Semrush, Google Search Console, or Google Keyword Planner before spending deeply on competitive pages.

## How to use this document

1. Read this entire `docs/seo-sprint.md` file.
2. Read `.seo/brand.md`, `.seo/link-inventory.md`, `.seo/keyword-research.json`, and `.seo/config.json`.
3. Find the next `pending` row in the Phase Status Tracker.
4. Execute one phase per PR.
5. In the same PR, update this tracker row to `completed` and update `.seo/link-inventory.md` when a new page ships.

Do not modify Reference Data, Conventions, Keyword Research Appendix, or phase ordering without an explicit product/SEO decision.

## Phase Status Tracker

| # | Phase | Pattern | Status | PR |
|---|---|---|---|---|
| 0 | Technical foundations: robots, sitemap reference, schema helpers | Setup | pending | - |
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

### Site facts

- **Domain:** https://rowset.lvtd.dev
- **Ahrefs project_id:** not configured
- **Domain Rating:** unknown in manual mode
- **Stack:** Django 6, Django templates, HTMX, Alpine.js, Tailwind/PostCSS
- **Marketing pages root:** `apps/pages`, `frontend/templates/pages`
- **Docs content root:** `apps/docs/content`
- **Sitemap generator:** `rowset/sitemaps.py`
- **Brand accent color:** `oklch(58% 0.16 158)`
- **Fonts:** Inter / system sans

### Existing programmatic surface

| Surface | URL pattern | Implementation |
|---|---|---|
| Use cases | `/use-cases/<slug>` | `apps/pages/use_cases.py`, `frontend/templates/pages/use-case-detail.html` |
| Docs | `/docs/<category>/<page>/` | `apps/docs/content`, `apps/docs/navigation.yaml`, docs templates |
| Blog | `/blog/<slug>` | `apps/blog`, blog templates |
| Sitemap | `/sitemap.xml` | `rowset/sitemaps.py` |
| Public agent skill | `/SKILL.md` | core skill-serving path |

### Critical files

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

Run date: 2026-07-03.

Command:

```text
uv run python /home/node/.openclaw/workspace/agent-control-plane-config/skills/seo-sprint/scripts/tech_audit.py --domain https://rowset.lvtd.dev --schema https://rowset.lvtd.dev/
```

Findings:

- `sitemap.xml` returns `200` and includes homepage, pricing, use cases, docs, and blog URLs.
- Production `robots.txt` returns `404`. This is the main Phase 0 fix.
- Local audit also found no `public/robots.txt` or `static/robots.txt`.
- Homepage has one H1, a canonical URL, a meta description, and `SoftwareApplication` JSON-LD.
- Sitemap-listed pages spot-check cleanly: one H1 per page, canonical URLs present, unique titles/descriptions in normal ranges.
- Sitemap response includes `X-Robots-Tag: noindex, noodp, noarchive`; review whether this header is inherited globally. It is less urgent than the missing robots file, but worth checking.

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

### A.1 - `/alternatives/[brand]` candidates

| Keyword | Page | Est. volume | Est. difficulty | Confidence | Notes |
|---|---|---:|---|---|---|
| airtable alternatives | `/alternatives/airtable` | 1000+ | high | high | Broad SERP; Rowset must narrow to AI-agent-managed datasets. |
| google sheets alternatives | `/alternatives/google-sheets` | 1000+ | high | high | Broad SERP; target users who need MCP/REST and private agent workflows. |
| baserow alternatives | `/alternatives/baserow` | 100-500 | medium | medium | Strong open-source/no-code database adjacency. |
| nocodb alternatives | `/alternatives/nocodb` | 100-500 | medium | medium | Good comparison angle: SQL UI vs agent backend. |

### A.2 - Existing use-case candidates

| Keyword | Existing URL | Est. volume | Est. difficulty | Confidence |
|---|---|---:|---|---|
| ai agent crm | `/use-cases/personal-crm` | 30-200 | medium | estimated |
| agent task board | `/use-cases/agent-task-board` | 30-200 | low-medium | estimated |
| feedback triage ai agent | `/use-cases/feedback-triage` | 10-100 | low | estimated |
| mcp dataset api | `/docs/features/mcp/` | 30-200 | low-medium | estimated |
| dataset api for ai agents | `/docs/api-reference/datasets/` | 30-200 | low-medium | estimated |

### A.3 - Compare candidates

| Keyword | Page | Est. volume | Est. difficulty | Confidence | Notes |
|---|---|---:|---|---|---|
| rowset vs airtable | `/compare/rowset-vs-airtable` | 0-30 now | low | estimated | Branded capture for later; useful sales asset. |
| rowset vs google sheets | `/compare/rowset-vs-google-sheets` | 0-30 now | low | estimated | Useful decision page for setup conversations. |
| airtable vs baserow | `/compare/airtable-vs-baserow` | 100-500 | medium-high | medium | High intent, but third-party commentary unless Rowset is clearly included as a different category. |

### A.4 - Playbook candidates

| Keyword | Page | Est. volume | Est. difficulty | Confidence |
|---|---|---:|---|---|
| connect ai agent to dataset api | `/playbooks/connect-ai-agent-to-dataset-api` | 30-200 | low-medium | estimated |
| mcp server for database | `/playbooks/mcp-server-for-database` | 100-500 | medium | estimated |
| agent managed feedback board | `/playbooks/agent-managed-feedback-board` | 10-100 | low | estimated |

### A.5 - Striking distance

Not available in manual mode. Add Google Search Console queries ranking positions 5-20 when GSC access is available.

### A.6 - Already-saturated head terms to avoid

- `database` - too broad and too competitive.
- `spreadsheet` - too broad and product positioning drift.
- `airtable alternative` - viable, but validate before targeting the singular variant; plural alternatives pages often capture broader demand.

## Phases

### Phase 0 - Technical foundations

**Why:** Google needs a clean crawl path before new content matters.

**Scope:**

1. Add a production `robots.txt` route or static file that allows crawling and references `https://rowset.lvtd.dev/sitemap.xml`.
2. Confirm `robots.txt` returns 200 on production after deploy.
3. Review why `sitemap.xml` is served with `X-Robots-Tag: noindex, noodp, noarchive`; remove inherited `noindex` header from sitemap responses if it is globally configured.
4. Add or centralize schema helpers for `SoftwareApplication`, `Organization`, `BreadcrumbList`, `FAQPage`, and `Article` if page-generating phases would otherwise duplicate JSON-LD.
5. Add `Organization` schema to the homepage if the helper exists.
6. Submit sitemap in Google Search Console and Bing Webmaster Tools.

**Files likely modified:**

- `apps/pages/urls.py` or a static file location for `robots.txt`
- `frontend/templates/base_landing.html` or a schema helper module/template
- `rowset/settings.py` only if headers need targeted sitemap handling
- `rowset/sitemaps.py` only if sitemap entries need adjustment

**Verification:**

```text
uv run python /home/node/.openclaw/workspace/agent-control-plane-config/skills/seo-sprint/scripts/tech_audit.py --domain https://rowset.lvtd.dev --schema https://rowset.lvtd.dev/
curl -sI https://rowset.lvtd.dev/robots.txt
curl -s https://rowset.lvtd.dev/robots.txt
curl -sI https://rowset.lvtd.dev/sitemap.xml
```

### Phase 1 - Strengthen existing use-case pages as the internal-link spine

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

**Scope:** direct, honest table comparing data model, agent setup, MCP, REST API, public sharing, pricing, and best-fit users.

### Phase 7 - Ship `/compare/rowset-vs-google-sheets`

**Why:** users need a simple "when not Sheets" decision page.

**Scope:** compare collaboration/spreadsheet strengths against agent backend strengths. Include where Sheets is still right.

### Phase 8 - Ship `/playbooks/connect-ai-agent-to-dataset-api`

**Why:** this turns Rowset's strongest workflow into a long-form page that can rank and convert.

**Scope:** explain setup, bearer-token handling, MCP discovery, first dataset creation, row updates, export, preview sharing, and privacy guardrails.

**Quality gate:** at least 2,500 words, Article schema, examples without exposing secrets.

### Phase 9 - Ship `/playbooks/agent-managed-feedback-board`

**Why:** feedback collection appeared in real Rowset usage and maps well to agent workflows.

**Scope:** dataset shape, index strategy, dedupe, customer links, status transitions, public preview, export.

### Phase 10 - Off-page starter submissions and backlink target list

**Why:** low-authority sites need links; programmatic pages alone will not rank for competitive alternatives terms.

**Scope:**

1. Prepare directory profiles: Product Hunt, AlternativeTo, SaaSHub, Indie Hackers, Crunchbase.
2. List Rowset as an alternative to Airtable, Google Sheets, Baserow, and NocoDB where appropriate and honest.
3. Build `.seo/backlink-targets.json` with listicles and MCP/database/agent-tool directories worth outreach.
4. Add a GSC/Bing submission checklist to the repo or ops notes after Phase 0 is deployed.

## Off-page Checklist

- [ ] Google Search Console property verified
- [ ] Sitemap submitted in GSC
- [ ] Bing Webmaster Tools property verified
- [ ] Sitemap submitted in Bing
- [ ] Product Hunt launch page planned
- [ ] AlternativeTo listing submitted
- [ ] SaaSHub listing submitted
- [ ] Indie Hackers product/profile update
- [ ] Crunchbase profile created or updated
- [ ] Backlink target list created at `.seo/backlink-targets.json`

## Glossary

- **DR** - Ahrefs Domain Rating, unknown until Ahrefs or another authority metric is connected.
- **KD** - keyword difficulty; manual mode uses rough high/medium/low labels.
- **Striking distance** - queries already ranking positions 5-20 in GSC.
- **Pattern A/B/C/D/E** - alternatives, use-case/audience, compare, playbook, and off-page phases.
