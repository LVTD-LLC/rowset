# Tags Column Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `tags` as a first-class semantic column type across Rowset's UI, REST, MCP, and CLI while preserving comma-separated row strings.

**Architecture:** Add the type to the shared dataset enum so existing schema normalization and every API boundary accept it. Derive a separate `tags` display list in the Django cell serializer and render it through one partial in authenticated and public table/detail templates; authenticated accent classes respect `choice_colorization_enabled`, while public pills stay neutral.

**Tech Stack:** Django 6, Django Ninja, FastMCP, Django templates, Tailwind/PostCSS, Go CLI, pytest.

## Global Constraints

- Store, return, filter, search, and export the original comma-separated string unchanged.
- Display parsing splits on commas, trims whitespace, and drops empty segments.
- Authenticated tag colors follow `profile.choice_colorization_enabled`; public pills are neutral.
- Do not add dependencies or migrations.
- Use Docker-backed `make test` for Python tests and `make cli-test` for Go tests.

---

### Task 1: Shared schema contract and agent-facing discovery

**Files:**
- Modify: `apps/datasets/choices.py`
- Modify: `apps/core/capabilities.py`
- Modify: `apps/api/schemas.py`
- Modify: `apps/mcp_server/server.py`
- Modify: `.agents/skills/rowset/SKILL.md`
- Modify: `.agents/skills/rowset-features/SKILL.md`
- Test: `apps/datasets/tests/test_csv_datasets.py`
- Test: `apps/mcp_server/tests/test_server.py`

**Interfaces:**
- Produces: `DatasetColumnType.TAGS == "tags"`; normalized schema `{\"type\": \"tags\"}`.
- Preserves: row values remain the exact strings supplied by callers.

- [ ] **Step 1: Write failing schema tests**

Add focused assertions that `normalize_column_schema(["topics"], {"topics": "tags"})`
returns `{"topics": {"type": "tags"}}`, `column_definitions` labels it `Tags`, and
an MCP schema exposes `tags` in the relevant tool descriptions.

- [ ] **Step 2: Run tests and verify RED**

Run: `make test apps/datasets/tests/test_csv_datasets.py apps/mcp_server/tests/test_server.py -- -k 'tags or column_type' -q`

Expected: FAIL because `tags` is unsupported or absent from descriptions.

- [ ] **Step 3: Add the minimal shared type and descriptions**

Add this enum member:

```python
class DatasetColumnType(models.TextChoices):
    TEXT = "text", "Text"
    TAGS = "tags", "Tags"
```

Add `tags` to each REST/MCP/capability/agent-skill supported-type list. Do not
add special storage validation: the existing text-like path is the intended
behavior.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/datasets/choices.py apps/core/capabilities.py apps/api/schemas.py apps/mcp_server/server.py .agents/skills/rowset/SKILL.md .agents/skills/rowset-features/SKILL.md apps/datasets/tests/test_csv_datasets.py apps/mcp_server/tests/test_server.py
git commit -m "feat: add tags semantic column type"
```

### Task 2: Shared tag display metadata and authenticated rendering

**Files:**
- Modify: `apps/datasets/views.py`
- Create: `frontend/templates/datasets/partials/tags_cell.html`
- Modify: `frontend/templates/datasets/dataset_detail.html`
- Modify: `frontend/templates/datasets/dataset_row_detail.html`
- Test: `apps/datasets/tests/test_csv_datasets.py`

**Interfaces:**
- Produces: `_tag_items(value: object, *, colorized: bool) -> list[dict[str, str]]`.
- Produces cell keys: `is_tags: bool`, `tags: list[{value, accent_class}]`.

- [ ] **Step 1: Write failing authenticated rendering tests**

Create a tags dataset with the stored value `" Django, HTMX, , django ,  "`.
Assert table and row-detail responses render four tag labels, omit empty
segments, retain the original string in edit form state, use empty accent
classes when the setting is false, and use deterministic nonempty classes when
the setting is true.

- [ ] **Step 2: Run tests and verify RED**

Run: `make test apps/datasets/tests/test_csv_datasets.py -- -k tags -q`

Expected: FAIL because cells have no tags display metadata or pill markup.

- [ ] **Step 3: Add minimal parsing and cell metadata**

Implement the display helper without mutating the source value:

```python
def _tag_items(value: object, *, colorized: bool) -> list[dict[str, str]]:
    items = []
    for segment in _cell_value(value).split(","):
        label = segment.strip()
        if not label:
            continue
        items.append({
            "value": label,
            "accent_class": _choice_value_accent_class(label) if colorized else "",
        })
    return items
```

Thread a `colorize_tags=False` keyword through `_row_cells` and
`_row_table_cells`. For `DatasetColumnType.TAGS`, set `is_tags` and `tags`.
Authenticated callers pass `request.user.profile.choice_colorization_enabled`.

- [ ] **Step 4: Render one shared partial**

Create `tags_cell.html` with a wrapping flex container and one `fb-choice-pill`
per item. Include it ahead of ordinary text rendering in both authenticated
templates. Use neutral base styling when `accent_class` is empty.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/datasets/views.py frontend/templates/datasets/partials/tags_cell.html frontend/templates/datasets/dataset_detail.html frontend/templates/datasets/dataset_row_detail.html apps/datasets/tests/test_csv_datasets.py
git commit -m "feat: render tags as profile-aware pills"
```

### Task 3: Public preview rendering

**Files:**
- Modify: `frontend/templates/datasets/public_dataset.html`
- Modify: `frontend/templates/datasets/public_dataset_row_detail.html`
- Test: `apps/datasets/tests/test_public_previews.py`

**Interfaces:**
- Consumes: shared `cell.is_tags`, `cell.tags`, and `tags_cell.html`.
- Preserves: public views never receive a profile color preference.

- [ ] **Step 1: Write failing public integration tests**

Add table and row-detail tests for `" Django, HTMX, ,  "`. Assert both labels
render as pills, empty segments do not render, and no `fb-choice-pill-*` accent
class appears.

- [ ] **Step 2: Run tests and verify RED**

Run: `make test apps/datasets/tests/test_public_previews.py -- -k tags -q`

Expected: FAIL because public templates still render the raw string.

- [ ] **Step 3: Include the shared partial in both public templates**

Add an `{% elif cell.is_tags %}` branch before ordinary text rendering and
include `datasets/partials/tags_cell.html`. Keep public view calls at the
default `colorize_tags=False`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/templates/datasets/public_dataset.html frontend/templates/datasets/public_dataset_row_detail.html apps/datasets/tests/test_public_previews.py
git commit -m "feat: render neutral tags in public previews"
```

### Task 4: CLI exposure, docs, and cross-surface verification

**Files:**
- Modify: `cli/internal/rowsetcli/cli_test.go`
- Modify: `cli/README.md`
- Modify: `apps/pages/content/docs/design-schema.md`
- Modify: `TECH.md`

**Interfaces:**
- Consumes: existing generic `--column-types` JSON forwarding.
- Proves: `{"topics":"tags"}` reaches REST unchanged.

- [ ] **Step 1: Change the CLI request test to exercise tags**

Add a `topics` header/value and `"topics":"tags"` to the create command test,
then assert the captured JSON body contains that exact schema and row string.

- [ ] **Step 2: Run the CLI test and verify the contract**

Run: `make cli-test`. Expected: PASS because the generic CLI transport already
supports tags without a code branch.

- [ ] **Step 3: Document the new supported type**

Update the CLI example, schema guide, and technical supported-type list to name
`tags`, explain comma-separated storage, and show `{"topics":"tags"}`.

- [ ] **Step 4: Run broad verification**

Run:

```bash
make test apps/datasets/tests/test_csv_datasets.py apps/datasets/tests/test_public_previews.py apps/api/tests.py apps/mcp_server/tests/test_server.py
make cli-test
npm run build
git diff --check
```

Expected: all commands succeed with no warnings introduced by this change.

- [ ] **Step 5: Commit**

```bash
git add cli/internal/rowsetcli/cli_test.go cli/README.md apps/pages/content/docs/design-schema.md TECH.md
git commit -m "docs: expose tags across Rowset clients"
```
