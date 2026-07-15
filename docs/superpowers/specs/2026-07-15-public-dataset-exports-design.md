# Public Dataset Exports

## Goal

Let anyone with access to an enabled public dataset preview download a complete snapshot in
the same formats available from the authenticated dataset UI: CSV, JSONL, XLSX, SQLite, and
Parquet.

## User Experience

An unlocked public dataset preview shows the existing Export menu beside the dataset heading.
Each menu item is a normal link to a public download URL. Downloads always contain the entire
dataset in stable export order; preview search, filters, sorting, and pagination do not change
the exported rows.

Locked password-protected previews do not show dataset metadata or export controls. After the
visitor unlocks the preview, the export menu appears and its downloads use the same session
access grant.

## HTTP Contract

Add a dedicated route:

```text
/share/datasets/<public_key>/export/<format>/
```

The route accepts the five existing export formats and delegates serialization, content type,
filename handling, and row iteration to the current dataset export response helper. Unsupported
formats return 404.

The route resolves only datasets that are public-enabled and not archived. A password-protected
dataset also requires the existing public-preview session grant. A direct request without that
grant returns 404, matching the current public asset-content boundary and avoiding disclosure of
protected dataset metadata.

Authenticated exports continue using their existing private-key route and ownership checks.

## Components and Boundaries

- `apps/datasets/urls.py` owns the dedicated public export URL.
- `apps/datasets/views.py` owns public dataset lookup and access enforcement, then calls the
  existing export response helper.
- `frontend/templates/components/dataset_export_menu.html` remains the single format menu and
  selects public or authenticated route names from explicit template context.
- `frontend/templates/datasets/public_dataset.html` includes the menu only when the visitor has
  access.
- Existing service serializers and `iter_export_row_data` remain unchanged.

No HTMX request is introduced because browser file downloads are already represented correctly
by ordinary links and do not update an HTML fragment.

## Error and Privacy Behavior

- Disabled public preview: 404.
- Archived dataset: 404.
- Unsupported format: 404.
- Locked password-protected preview: 404 from the export route.
- Unlocked password-protected preview: normal download.
- Export responses do not expose private dataset keys or require authenticated credentials.

## Testing

Use Django outside-in TDD in `apps/datasets/tests/test_public_previews.py`:

1. Prove an unlocked public preview renders links for all five formats.
2. Prove each public route returns a downloadable response with the existing format contract.
3. Prove exports contain the full dataset even when query parameters resemble preview filters.
4. Prove disabled and archived datasets return 404.
5. Prove unsupported formats return 404.
6. Prove a password-protected export is unavailable before unlock and succeeds afterward.

Run the focused public-preview tests first, followed by the focused dataset export tests because
the shared response helper and menu are used by both public and authenticated flows.

## Non-Goals

- Exporting only the current filtered, sorted, or paginated preview.
- Adding new export formats or changing serialization.
- Adding signed or expiring download URLs.
- Making private REST or MCP dataset access public.
- Tracking download analytics or adding export-specific public settings.
