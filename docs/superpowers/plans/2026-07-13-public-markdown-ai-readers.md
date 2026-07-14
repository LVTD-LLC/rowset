# Public Markdown and AI Readers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish clean Markdown variants for Rowset-owned public pages, add AI-reader actions to docs and blog posts, and rebuild `llms.txt` as an app-use documentation index.

**Architecture:** Add a focused `apps.pages.public_markdown` service for Markdown loading, URL/prompt construction, and responses. Existing docs/use-case/blog Markdown stays canonical; template-only pages receive curated files under `apps/pages/content/public`. Django views expose paired extensionless and `.md` routes, while one Alpine component owns the local dropdown/copy behavior.

**Tech Stack:** Django 6, Python 3.14, python-frontmatter, Django templates, Alpine.js 3, HTMX-compatible server-rendered templates, pytest.

## Global Constraints

- Do not add dependencies.
- Markdown responses use `text/markdown; charset=utf-8` and never include YAML frontmatter or site chrome.
- Exclude auth/account pages and user-generated public dataset previews.
- Never expose API keys, secrets, or private dataset content.
- Use extensionless UI routes and `.md` machine-readable siblings; homepage Markdown is `/index.md`.
- Keep the menu local to Alpine.js; HTMX owns no state for this component.
- Use Docker-backed `make test` for authoritative Django verification.

---

### Task 1: Public Markdown service and route pairs

**Files:**
- Create: `apps/pages/public_markdown.py`
- Modify: `apps/pages/content.py`
- Modify: `apps/pages/views.py`
- Modify: `apps/pages/urls.py`
- Test: `apps/pages/tests.py`
- Test: `apps/pages/test_blog.py`

**Interfaces:**
- Produces: `render_content_markdown(section_slug: str, page_slug: str) -> str`
- Produces: `render_blog_markdown(post: BlogPost) -> str`
- Produces: `markdown_path_for(path: str) -> str`
- Produces: `markdown_response(content: str) -> HttpResponse`
- Produces: Django URL names `public_page_markdown`, `content_page_markdown`, and `blog_post_markdown`

- [ ] **Step 1: Write failing route and response tests**

Add Django-client tests that assert `/index.md`, `/pricing.md`, `/docs/quickstart.md`,
`/use-cases/personal-crm.md`, and `/blog/<slug>.md` return status 200 and
`text/markdown; charset=utf-8`; assert docs template variables are rendered, YAML frontmatter is
absent, blog output begins with the post title, and missing slugs return 404.

- [ ] **Step 2: Run the focused tests and observe red**

Run:

```bash
make test apps/pages/tests.py apps/pages/test_blog.py -- -k markdown -q
```

Expected: failures are 404s or missing URL names because the Markdown routes do not exist.

- [ ] **Step 3: Implement minimal loaders and responses**

Create `apps/pages/public_markdown.py` with path-safe file loading and these core contracts:

```python
MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"

def markdown_path_for(path: str) -> str:
    if path == "/":
        return "/index.md"
    return f"{path.rstrip('/')}.md"

def markdown_response(content: str) -> HttpResponse:
    return HttpResponse(f"{content.rstrip()}\n", content_type=MARKDOWN_CONTENT_TYPE)
```

Refactor the content-file read in `apps/pages/content.py` into a shared loader that returns parsed
frontmatter plus rendered Markdown. Reuse `get_blog_post()` and `BlogPost.content` for blog output.
Add explicit `.md` URL patterns before the extensionless content patterns, and normalize in-scope UI
routes to extensionless paths.

- [ ] **Step 4: Run focused tests and observe green**

Run the command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Commit the route/service slice**

```bash
git add apps/pages/public_markdown.py apps/pages/content.py apps/pages/views.py apps/pages/urls.py apps/pages/tests.py apps/pages/test_blog.py
git commit -m "feat(pages): publish markdown route variants"
```

### Task 2: Curated Markdown for template-only public pages

**Files:**
- Create: `apps/pages/content/public/index.md`
- Create: `apps/pages/content/public/pricing.md`
- Create: `apps/pages/content/public/privacy-policy.md`
- Create: `apps/pages/content/public/terms-of-service.md`
- Create: `apps/pages/content/public/uses.md`
- Create: `apps/pages/content/public/blog.md`
- Modify: `apps/pages/public_markdown.py`
- Test: `apps/pages/tests.py`

**Interfaces:**
- Consumes: `markdown_response()` and `markdown_path_for()` from Task 1
- Produces: `CURATED_PUBLIC_PAGE_SOURCES: dict[str, str]` mapping stable page keys to checked-in files

- [ ] **Step 1: Strengthen the failing public-page inventory test**

Parameterize every static in-scope page key and assert its `.md` response contains a page-specific
heading and no `<html`, `<nav`, or YAML delimiter at the beginning.

- [ ] **Step 2: Run the inventory test and observe red**

```bash
make test apps/pages/tests.py -- -k public_markdown_inventory -q
```

Expected: each missing curated source fails with 404 or missing expected content.

- [ ] **Step 3: Add curated sources and registry entries**

Write concise, accurate Markdown reflecting the useful content of each HTML page. Preserve the full
legal meaning of privacy and terms pages. Use only public template variables from
`get_content_template_context()` when a URL is dynamic. Register the standalone database MCP guide
against its existing canonical docs Markdown rather than duplicating the large HTML template.

- [ ] **Step 4: Run inventory and existing page tests**

```bash
make test apps/pages/tests.py -- -k "public_markdown_inventory or landing or pricing or privacy or terms" -q
```

Expected: selected tests pass.

- [ ] **Step 5: Commit curated public content**

```bash
git add apps/pages/content/public apps/pages/public_markdown.py apps/pages/tests.py
git commit -m "content: add public page markdown sources"
```

### Task 3: Accessible AI-reader menu

**Files:**
- Create: `frontend/templates/components/ai_reader_menu.html`
- Modify: `apps/pages/public_markdown.py`
- Modify: `apps/pages/content.py`
- Modify: `apps/pages/views.py`
- Modify: `frontend/templates/pages/content/page.html`
- Modify: `frontend/templates/blog/blog_post.html`
- Modify: `frontend/templates/pages/explanations/database-mcp-server.html`
- Modify: `frontend/src/js/alpine-components.js`
- Test: `apps/pages/tests.py`
- Test: `apps/pages/test_blog.py`

**Interfaces:**
- Produces: `build_ai_reader_context(path: str) -> dict[str, str]`
- Produces: Alpine component `aiReaderMenu`
- Consumes: existing `window.Rowset.copyTextToClipboard()`

- [ ] **Step 1: Write failing server-rendered contract tests**

For a docs page, standalone database guide, and blog post, assert the response contains exactly the
four requested labels, a real button with `aria-expanded`, the absolute `.md` URL, and provider
links whose decoded `q` parameter equals:

```text
Read this Rowset page and help me understand or use it: <absolute Markdown URL>
```

Assert the blog index and use-case pages do not render this menu.

- [ ] **Step 2: Run menu tests and observe red**

```bash
make test apps/pages/tests.py apps/pages/test_blog.py -- -k ai_reader -q
```

Expected: labels/context are absent.

- [ ] **Step 3: Add context helper and shared template**

Implement provider links centrally:

```python
prompt = f"Read this Rowset page and help me understand or use it: {markdown_url}"
query = urlencode({"q": prompt})
return {
    "markdown_url": markdown_url,
    "ai_reader_prompt": prompt,
    "claude_url": f"https://claude.ai/new?{query}",
    "chatgpt_url": f"https://chatgpt.com/?{query}",
}
```

Render one component include in docs, the database explanation, and blog posts. Use `x-cloak`,
`@click.outside`, `@keydown.escape`, and bound `aria-expanded` for accessible local state.

- [ ] **Step 4: Implement copy behavior in Alpine**

Register `aiReaderMenu` with `open`, `busy`, and transient `status`. `copyPrompt()` copies the
server-provided prompt. `copyMarkdown()` fetches the server-provided Markdown URL with
`credentials: "same-origin"`, requires `response.ok`, copies the body, and surfaces failure without
using `x-html`.

- [ ] **Step 5: Run menu tests, lint, and build**

```bash
make test apps/pages/tests.py apps/pages/test_blog.py -- -k ai_reader -q
npm run lint
npm run build
```

Expected: Django tests pass, ESLint exits 0, and the asset build exits 0.

- [ ] **Step 6: Commit the AI-reader slice**

```bash
git add apps/pages/public_markdown.py apps/pages/content.py apps/pages/views.py frontend/templates/components/ai_reader_menu.html frontend/templates/pages/content/page.html frontend/templates/blog/blog_post.html frontend/templates/pages/explanations/database-mcp-server.html frontend/src/js/alpine-components.js apps/pages/tests.py apps/pages/test_blog.py
git commit -m "feat(pages): add AI reader actions"
```

### Task 4: App-use-first `llms.txt`

**Files:**
- Create: `apps/pages/llms.py`
- Modify: `apps/pages/views.py`
- Modify: `apps/pages/urls.py`
- Modify: `apps/core/urls.py`
- Modify: `apps/core/views.py`
- Modify: `apps/core/capabilities.py`
- Test: `apps/pages/tests.py`
- Test: `apps/core/tests/test_views.py`

**Interfaces:**
- Consumes: `get_content_section("docs")`, `get_content_section("use-cases")`, and Markdown URL helpers
- Produces: `render_llms_txt() -> str`
- Moves: URL name `llms_txt` from `apps.core` ownership to `apps.pages` without changing the name

- [ ] **Step 1: Write a failing complete-inventory test**

Build the expected docs list from `get_content_section("docs")["pages"]`. Assert every page has an
absolute `.md` link in `llms.txt`, quickstart appears before other docs, use cases are linked, MCP and
REST surfaces remain present, and capability-detail dumps such as `MCP tools:` are absent.

- [ ] **Step 2: Run the `llms.txt` tests and observe red**

```bash
make test apps/pages/tests.py apps/core/tests/test_views.py -- -k llms_txt -q
```

Expected: the current capability dump does not include the docs inventory and still contains
capability-detail sections.

- [ ] **Step 3: Implement the pages-owned discovery renderer**

Create `apps/pages/llms.py` that renders overview, app-use guidance, quickstart, complete docs,
use cases, and MCP/REST/skill links from existing registries. Keep `apps.core.capabilities` focused
on capability payloads by removing its old `render_rowset_llms_txt()` function. Move the route and
view to `apps.pages` while preserving `reverse("llms_txt")`.

- [ ] **Step 4: Run focused discovery tests**

Run the command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Commit the discovery slice**

```bash
git add apps/pages/llms.py apps/pages/views.py apps/pages/urls.py apps/core/urls.py apps/core/views.py apps/core/capabilities.py apps/pages/tests.py apps/core/tests/test_views.py
git commit -m "feat(pages): make llms index app documentation"
```

### Task 5: Integrated verification and shipping readiness

**Files:**
- Modify only files required by failures found during verification.

**Interfaces:**
- Consumes all prior tasks.
- Produces a reviewed, locally verified branch ready for PR creation.

- [ ] **Step 1: Run focused page tests**

```bash
make test apps/pages/tests.py apps/pages/test_blog.py apps/core/tests/test_views.py
```

Expected: zero failures.

- [ ] **Step 2: Run frontend and Django checks**

```bash
npm run lint
npm run build
make manage check
```

Expected: every command exits 0.

- [ ] **Step 3: Run the local CI-equivalent suite**

```bash
make ci-local
```

Expected: every configured CI-equivalent check exits 0.

- [ ] **Step 4: Inspect route coverage and diff hygiene**

```bash
git diff --check origin/main...HEAD
git status --short
```

Expected: no whitespace errors and no unintended generated or secret files.

- [ ] **Step 5: Commit any verification fixes**

```bash
git add apps/pages apps/core frontend/src/js/alpine-components.js frontend/templates
git commit -m "fix(pages): address public markdown verification"
```

Skip this commit when verification required no changes.
