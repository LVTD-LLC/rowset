# Public Dataset Exports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let visitors with access to a public dataset download a complete snapshot in every format supported by authenticated dataset exports.

**Architecture:** Add a dedicated public-key export route that applies the existing public-preview availability and password-session checks before delegating to the existing export response helper. Reuse the current export menu with an explicit public/private route context, keeping downloads as ordinary links rather than HTMX requests.

**Tech Stack:** Django 6 views and URL routing, Django templates, pytest-django, existing Rowset export serializers.

## Global Constraints

- Public exports include the entire dataset and ignore preview filters, sorting, and pagination.
- Supported formats are exactly CSV, JSONL, XLSX, SQLite, and Parquet.
- Disabled, archived, and locked password-protected public datasets return 404 from export URLs.
- Authenticated export routes and ownership checks remain unchanged.
- Reuse `DATASET_EXPORT_FORMATS`, `_dataset_export_response`, and `iter_export_row_data`; do not duplicate serialization.
- Use normal download links; do not add HTMX or JavaScript.
- Do not add dependencies or migrations.

---

### Task 1: Public Export Route and Access Boundary

**Files:**
- Modify: `apps/datasets/tests/test_public_previews.py`
- Modify: `apps/datasets/urls.py:119-129`
- Modify: `apps/datasets/views.py:2841-2861`

**Interfaces:**
- Consumes: `_dataset_export_response(dataset: Dataset, export_format: str) -> HttpResponse` and `_has_public_dataset_access(request, dataset: Dataset) -> bool` from `apps/datasets/views.py`.
- Produces: URL name `public_dataset_export` with arguments `(public_key, export_format)` and view `public_dataset_export(request, public_key, export_format)`.

- [ ] **Step 1: Add imports and failing route/format tests**

Add these imports to `apps/datasets/tests/test_public_previews.py`:

```python
import csv
import io

from django.utils import timezone
```

Add tests that use the literal intended URL so the red run returns 404 rather than failing URL reversal:

```python
PUBLIC_EXPORT_CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "jsonl": "application/x-ndjson; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "sqlite": "application/vnd.sqlite3",
    "parquet": "application/vnd.apache.parquet",
}


@pytest.mark.parametrize(("export_format", "content_type"), PUBLIC_EXPORT_CONTENT_TYPES.items())
def test_public_dataset_exports_supported_formats(client, profile, export_format, content_type):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])

    response = client.get(f"{dataset.get_public_url()}export/{export_format}/")

    assert response.status_code == 200
    assert response["Content-Type"] == content_type
    assert response["Content-Disposition"].endswith(f'.{export_format}"')


def test_public_dataset_export_contains_all_rows_despite_preview_query(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.public_page_size = 1
    dataset.save(update_fields=["public_enabled", "public_page_size"])

    response = client.get(
        f"{dataset.get_public_url()}export/csv/",
        {"row_q": "Ada", "page": "1"},
    )

    exported = list(csv.DictReader(io.StringIO(response.content.decode())))
    assert exported == [
        {"name": "Ada", "email": "ada@example.com"},
        {"name": "Grace", "email": "grace@example.com"},
    ]
```

- [ ] **Step 2: Run the new route tests and verify RED**

Run:

```bash
make test apps/datasets/tests/test_public_previews.py -- -k "public_dataset_export" -q
```

Expected: FAIL because `/share/datasets/<public_key>/export/<format>/` returns 404 instead of 200.

- [ ] **Step 3: Add failing privacy and error-boundary tests**

Add:

```python
@pytest.mark.parametrize("dataset_state", ["disabled", "archived"])
def test_public_dataset_export_requires_active_public_preview(client, profile, dataset_state):
    dataset = create_ready_dataset(profile)
    if dataset_state == "archived":
        dataset.public_enabled = True
        dataset.archived_at = timezone.now()
        dataset.save(update_fields=["public_enabled", "archived_at"])

    response = client.get(f"{dataset.get_public_url()}export/csv/")

    assert response.status_code == 404


def test_public_dataset_export_rejects_unsupported_format(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])

    response = client.get(f"{dataset.get_public_url()}export/xml/")

    assert response.status_code == 404


def test_public_dataset_export_requires_password_unlock(auth_client, client, profile):
    dataset = create_ready_dataset(profile)
    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "secret-table",
        },
    )
    dataset.refresh_from_db()
    export_url = f"{dataset.get_public_url()}export/csv/"

    locked_response = client.get(export_url)
    assert locked_response.status_code == 404

    unlock_response = client.post(dataset.get_public_url(), {"password": "secret-table"})
    assert unlock_response.status_code == 302

    unlocked_response = client.get(export_url)
    assert unlocked_response.status_code == 200
    assert unlocked_response["Content-Type"] == "text/csv; charset=utf-8"
```

- [ ] **Step 4: Add the dedicated route and minimal public export view**

Add the route before the public row-detail route in `apps/datasets/urls.py`:

```python
path(
    "share/datasets/<uuid:public_key>/export/<str:export_format>/",
    views.public_dataset_export,
    name="public_dataset_export",
),
```

Add the view after `_has_public_dataset_access` in `apps/datasets/views.py`:

```python
@require_http_methods(["GET", "HEAD"])
def public_dataset_export(request, public_key, export_format):
    dataset = get_object_or_404(
        Dataset,
        public_key=public_key,
        public_enabled=True,
        archived_at__isnull=True,
    )
    if not _has_public_dataset_access(request, dataset):
        raise Http404("Dataset export not found.")
    return _dataset_export_response(dataset, export_format)
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
make test apps/datasets/tests/test_public_previews.py -- -k "public_dataset_export" -q
```

Expected: all selected public export tests PASS. Confirm that the unsupported format test reaches `_dataset_export_response` and returns 404.

- [ ] **Step 6: Commit the public export boundary**

```bash
git add apps/datasets/tests/test_public_previews.py apps/datasets/urls.py apps/datasets/views.py
git commit -m "feat(datasets): add public dataset export route"
```

---

### Task 2: Shared Export Menu on Public Preview

**Files:**
- Modify: `apps/datasets/tests/test_public_previews.py`
- Modify: `frontend/templates/components/dataset_export_menu.html:1-33`
- Modify: `frontend/templates/datasets/public_dataset.html:11-17`

**Interfaces:**
- Consumes: URL name `public_dataset_export(public_key, export_format)` from Task 1.
- Produces: `dataset_export_menu.html` template context flag `public_export=True`; absent/false preserves private route generation.

- [ ] **Step 1: Write failing public menu tests**

Add:

```python
def test_public_dataset_preview_links_all_export_formats(client, profile):
    dataset = create_ready_dataset(profile)
    dataset.public_enabled = True
    dataset.save(update_fields=["public_enabled"])

    response = client.get(dataset.get_public_url())
    content = response.content.decode()

    assert response.status_code == 200
    assert 'aria-label="Export dataset"' in content
    for export_format in PUBLIC_EXPORT_CONTENT_TYPES:
        export_url = reverse(
            "public_dataset_export",
            args=[dataset.public_key, export_format],
        )
        assert f'href="{export_url}"' in content
    assert str(dataset.key) not in content


def test_locked_public_dataset_preview_hides_export_menu(auth_client, client, profile):
    dataset = create_ready_dataset(profile)
    auth_client.post(
        reverse("dataset_update_public_settings", args=[dataset.key]),
        {
            "public_enabled": "on",
            "public_page_size": "10",
            "public_password": "secret-table",
        },
    )
    dataset.refresh_from_db()

    response = client.get(dataset.get_public_url())

    assert response.status_code == 200
    assert 'aria-label="Export dataset"' not in response.content.decode()
```

- [ ] **Step 2: Run menu tests and verify RED**

Run:

```bash
make test apps/datasets/tests/test_public_previews.py -- -k "export_menu or links_all_export_formats" -q
```

Expected: the unlocked-preview test FAILS because no public export menu is rendered. The locked-preview assertion passes as characterization evidence.

- [ ] **Step 3: Make the existing menu select public or private URLs**

At the top of `frontend/templates/components/dataset_export_menu.html`, resolve all URLs from explicit context:

```django
{% if public_export %}
  {% url 'public_dataset_export' dataset.public_key 'csv' as csv_export_url %}
  {% url 'public_dataset_export' dataset.public_key 'jsonl' as jsonl_export_url %}
  {% url 'public_dataset_export' dataset.public_key 'xlsx' as xlsx_export_url %}
  {% url 'public_dataset_export' dataset.public_key 'sqlite' as sqlite_export_url %}
  {% url 'public_dataset_export' dataset.public_key 'parquet' as parquet_export_url %}
{% else %}
  {% url 'dataset_export' dataset.key 'csv' as csv_export_url %}
  {% url 'dataset_export' dataset.key 'jsonl' as jsonl_export_url %}
  {% url 'dataset_export' dataset.key 'xlsx' as xlsx_export_url %}
  {% url 'dataset_export' dataset.key 'sqlite' as sqlite_export_url %}
  {% url 'dataset_export' dataset.key 'parquet' as parquet_export_url %}
{% endif %}
```

Replace only the five hard-coded `{% url ... %}` expressions in the link `href` attributes with:

```django
{{ csv_export_url }}
{{ jsonl_export_url }}
{{ xlsx_export_url }}
{{ sqlite_export_url }}
{{ parquet_export_url }}
```

Keep all existing labels, descriptions, ordering, CSS classes, and Alpine menu behavior unchanged.

- [ ] **Step 4: Render the menu in the unlocked public heading**

Replace the unlocked heading wrapper in `frontend/templates/datasets/public_dataset.html` with:

```django
<div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
  <div class="min-w-0">
    <p class="fb-label-caps text-emerald-600 dark:text-emerald-400">Shared Rowset dataset</p>
    <h1 class="fb-page-title mt-2 break-words">{{ dataset.name }}</h1>
    <p class="mt-2 text-sm text-slate-600 dark:text-slate-300">{{ dataset.row_count }} rows · {{ dataset.headers|length }} columns</p>
  </div>
  <div class="shrink-0">
    {% include "components/dataset_export_menu.html" with public_export=True %}
  </div>
</div>
```

- [ ] **Step 5: Run public and authenticated menu tests and verify GREEN**

Run:

```bash
make test apps/datasets/tests/test_public_previews.py -- -k "export_menu or links_all_export_formats" -q
make test apps/datasets/tests/test_csv_datasets.py -- -k "dataset_export and not api" -q
```

Expected: all selected tests PASS, including authenticated export downloads that prove the shared menu/view changes did not alter the private contract.

- [ ] **Step 6: Commit the public export menu**

```bash
git add apps/datasets/tests/test_public_previews.py frontend/templates/components/dataset_export_menu.html frontend/templates/datasets/public_dataset.html
git commit -m "feat(datasets): show exports on public previews"
```

---

### Task 3: Integrated Verification

**Files:**
- Verify only; no planned modifications.

**Interfaces:**
- Consumes: the public route/access contract from Task 1 and shared menu behavior from Task 2.
- Produces: fresh verification evidence for the complete feature.

- [ ] **Step 1: Run the complete public-preview test module**

```bash
make test apps/datasets/tests/test_public_previews.py
```

Expected: PASS with zero failures.

- [ ] **Step 2: Run the focused existing export regression set**

```bash
make test apps/datasets/tests/test_csv_datasets.py -- -k "dataset_export and not api" -q
```

Expected: PASS with zero failures.

- [ ] **Step 3: Check formatting and the final diff**

```bash
git diff --check HEAD~2..HEAD
git status --short
```

Expected: `git diff --check` exits 0 and `git status --short` is empty.

- [ ] **Step 4: Review requirements against the diff**

Confirm all five formats appear in the public menu, every public download uses the public key,
full-row export iteration is unchanged, locked/disabled/archived access is denied, and private
export URLs still use the dataset key. If verification requires a correction, add a focused
failing test before changing behavior and commit the correction separately.
