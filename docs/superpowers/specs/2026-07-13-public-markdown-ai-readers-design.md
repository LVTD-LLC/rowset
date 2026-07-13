# Public Markdown and AI Readers Design

## Goal

Give every Rowset-owned public marketing or content page a clean Markdown representation, make
docs and blog posts easy to hand to AI tools, and turn `llms.txt` into a practical index for using
Rowset.

## Scope

The publishing surface includes the landing page, pricing, privacy policy, terms of service,
legacy public informational pages, use-case pages, docs pages, the blog index, blog posts, and the
standalone database MCP explanation.

Authenticated pages, account flows, API responses, MCP endpoints, and user-generated public
dataset previews are excluded. The feature must not expose user data, credentials, or private
application state.

## Routes and response contract

Public UI routes use extensionless paths. The same path with a `.md` suffix returns Markdown:

- `/pricing` and `/pricing.md`
- `/docs/quickstart` and `/docs/quickstart.md`
- `/blog/agent-managed-datasets` and `/blog/agent-managed-datasets.md`
- `/use-cases/personal-crm` and `/use-cases/personal-crm.md`

The homepage Markdown route is `/index.md`. Directory index pages use the section name, such as
`/blog.md` and `/use-cases.md`.

Markdown responses use `text/markdown; charset=utf-8`. They contain the page's useful content,
with a single top-level title where appropriate, but no YAML frontmatter, HTML shell, navigation,
analytics, or structured-data scripts. Missing or invalid content returns 404 using the same
validation boundary as the UI route.

No redirects or compatibility aliases are required. Existing public UI URLs may be normalized as
part of the change.

## Content architecture

`apps.pages` owns one public Markdown service that resolves a page identity to rendered Markdown.
The service has three source paths:

1. Docs and use cases load their checked-in Markdown, strip frontmatter, and render the existing
   safe public Django template variables.
2. Blog posts load their validated checked-in Markdown body and prepend the post title and
   description so the standalone document is self-describing.
3. Template-only public pages load curated checked-in Markdown counterparts. These files describe
   the useful product content without trying to reproduce decorative layout or navigation.

The HTML views and Markdown views share loaders and validation. They do not convert rendered HTML
back to Markdown, and no new conversion dependency is added.

Each HTML content view receives its canonical Markdown URL in template context. URL construction is
centralized so templates, AI prompts, `llms.txt`, and tests cannot invent different suffix rules.

## AI reader menu

Every docs page and individual blog post shows a `Read with AI` dropdown at the top of the content.
The menu is an accessible local-state component owned by Alpine.js. It uses a real button,
`aria-expanded`, keyboard focus, outside-click dismissal, and Escape dismissal. It does not make an
HTMX request or persist state.

The menu contains exactly these actions:

- Read with Claude
- Read with ChatGPT
- Copy Prompt for your AI Agent
- Copy Markdown

The shared prompt is:

```text
Read this Rowset page and help me understand or use it: <absolute Markdown URL>
```

Claude and ChatGPT links open a new tab with that URL-encoded prompt. Provider URL construction is
kept in one Python helper because neither vendor documents a durable prefill-link contract. Copy
Prompt copies the same plain-text prompt. Copy Markdown fetches the Markdown URL with same-origin
credentials and copies the response body. Copy feedback reuses Rowset's existing clipboard helper
and reports `Copied` or `Copy failed` without replacing the menu labels permanently.

## `llms.txt`

`llms.txt` is a concise discovery index, not a concatenation of every document. It starts with a
short statement of what Rowset does and how an agent should use it, then includes:

- the quickstart first;
- every routed docs page as an absolute `.md` link with its description;
- the use-case index and routed use-case Markdown links;
- hosted MCP, REST API base, OpenAPI docs, and Rowset skill links;
- product overview links only when they help an agent choose the correct application path.

The file emphasizes authenticated MCP first, REST second, and public previews only for read-only
human review. It must not imply that browser automation or public previews replace authenticated
agent access.

## Error handling and security

All file-backed lookups validate slugs and resolved paths before reading. Django template rendering
inside Markdown receives only the existing allowlisted public context. Provider prompts contain
only public Markdown URLs. Clipboard fetch failures stay local to the control and never inject
untrusted HTML.

## Testing

Outside-in Django tests cover representative route pairs, content types, source rendering,
frontmatter removal, 404 behavior, canonical Markdown URLs, the docs/blog menu, and the full
`llms.txt` docs inventory. Focused helper tests cover suffix and provider-link construction.

Browser behavior uses the smallest available proof: server-rendered accessibility and data
contracts plus lint/build verification for the Alpine component. The repository has no JavaScript
test runner, so adding one solely for this dropdown is out of scope; real-page wiring is verified
through Django integration tests and a browser smoke check.

## Definition of done

- Every in-scope public page has a working Markdown route.
- Docs pages and blog posts render all four AI actions with a shared prompt contract.
- `llms.txt` indexes every docs Markdown route and the primary app-use surfaces.
- Focused Django tests, frontend lint/build, and the appropriate broad local checks pass.
- The pull request is conflict-free, ready for review, CI-green, has no unresolved review feedback,
  and Greptile reports 5/5 confidence.
