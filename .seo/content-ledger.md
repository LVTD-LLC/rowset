# SEO Content Ledger

## Shipped

| Date | Type | Title | Slug | Target Keyword | Primary Internal Links | Notes |
| --- | --- | --- | --- | --- | --- | --- |

## Candidate Backlog

Last researched: 2026-06-30

| Rank | Score | Proposed Type | Title | Target Keyword | Intent | SERP Read | Why It Fits |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| 1 | 20 | Comparison / implementation guide | MCP vs REST API for AI Agents: When Your Dataset Needs Both | mcp vs rest api | Commercial investigation / technical evaluation | Current results are mostly general explainers about MCP wrapping APIs, with room for a dataset-specific implementation angle. | Maps directly to Rowset's dual MCP + REST promise and can convert to setup/API docs. |
| 2 | 18 | Alternative / problem-solution | Stop Using Google Sheets as Your AI Agent's Database | google sheets api ai agents | Problem-aware / alternative search | Results include tutorials for connecting agents to Sheets, but less on failure modes and safer structured-data backends. | Frames Rowset as the stable backend when Sheets is too fragile for agent-owned row operations. |
| 3 | 17 | How-to | How to Give an AI Agent a Private Dataset API | ai agent api data access | Informational / implementation | SERPs skew broad around APIs, MCP servers, and data access. A precise private dataset API tutorial can add information gain. | Strong setup path: create API key, connect MCP/REST, create dataset, verify rows. |
| 4 | 15 | Checklist | AI Agent Data Access Checklist: Auth, Ownership, Logs, and Public Sharing | ai agent data access | Informational / security-aware | Results discuss MCP/API security and agent data infrastructure at a high level. | Lets Rowset own the private-by-default and public-preview boundary. |
| 5 | 14 | Use-case guide | Agent-Managed Datasets for Lead Lists, Research Logs, and Ops Trackers | ai agent structured data | Informational / use-case exploration | Results are broad around structured data agents and data infrastructure. | Turns abstract structured-data intent into concrete Rowset dataset examples. |

## SEO/Content Traction Plan

### Goal

- Traction goal: prove whether technical operators searching for agent data/API
  workflows will sign up or copy a Rowset setup prompt.
- Target customer: founders, operators, analysts, and engineers delegating
  structured-data work to trusted AI agents.
- Conversion event: signup, API key creation, setup prompt copy, or docs click to
  MCP/API setup pages.

### Strategy

- Organic strategy: a narrow content marketing + long-tail SEO blend around
  agent-managed datasets, MCP/REST integration, and practical alternatives to
  spreadsheet-backed agent workflows.
- Why this can move the needle: Rowset has a concrete product surface where
  generic MCP/API content is often abstract. Posts can show exact dataset, row,
  auth, preview, and export workflows.

### Page/Post Plan

| Asset | Intent | Angle | Promotion | Conversion Path |
| --- | --- | --- | --- | --- |
| MCP vs REST API for AI Agents: When Your Dataset Needs Both | Compare integration choices | MCP is the agent interface; REST is the deterministic system interface; datasets often need both. | Share with MCP/API communities and link from docs. | Blog -> `/docs/features/mcp/` + `/docs/api-reference/introduction/` -> signup/setup prompt. |
| Stop Using Google Sheets as Your AI Agent's Database | Find a safer alternative | Sheets is useful for humans, fragile as an agent-owned data backend. | Share as a practical operator post; pitch as Google Sheets MCP counter-position. | Blog -> `/docs/features/datasets/` -> signup/setup prompt. |
| How to Give an AI Agent a Private Dataset API | Implementation how-to | Walk through bearer key setup, dataset creation, row CRUD, and public preview review. | Use as docs-adjacent launch/tutorial post. | Blog -> `/docs/getting-started/introduction/` -> API key creation. |

### Measurement

| Metric | Target | Tool/Method |
| --- | --- | --- |
| Setup prompt copies from blog sessions | 3+ in first 30 days across initial posts | PostHog event with referrer/path. |
| Signup or login from blog sessions | 5+ in first 30 days | PostHog/Plausible path analysis. |
| Docs clicks from blog posts | 20+ qualified clicks in first 30 days | Plausible outbound/internal path funnel. |
| Indexed pages | All published posts indexed, no drafts indexed | Sitemap + Search Console spot checks. |
| Assisted mentions/links | 2+ relevant shares or backlinks | Manual tracking in this ledger. |

### Decision Rules

- Double down: posts drive setup prompt copies or API-key/setup docs traffic, even
  at low absolute volume.
- Iterate: posts get impressions/clicks but no setup actions; tighten CTAs and
  add stronger worked examples.
- Kill: content gets low impressions and no qualified product actions after three
  focused posts and promotion attempts.

## Notes

- Keyword/SERP source: light web SERP scan on 2026-06-30 for MCP vs REST,
  AI-agent structured data, and Google Sheets/API agent workflows.
- Future pass should use DataForSEO once credentials are available in the runtime
  for volume, difficulty, and related-query expansion.
- Keep Rowset content honest: Rowset stores owned structured datasets over MCP
  and REST; agents may read upstream sources themselves, but Rowset should not
  claim native source sync that is not implemented.
