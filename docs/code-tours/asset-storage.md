# Dataset Asset Storage Flow

Use this tour before changing image columns, dataset asset upload/download,
private asset storage, cleanup retry rows, or public preview asset URLs.

## Files To Inspect

- `rowset/settings.py` - `STORAGES["dataset_assets"]` chooses local private
  storage unless `ROWSET_ASSET_S3_ENDPOINT_URL` is configured.
- `rowset/storages.py` - S3-compatible storage URL behavior for local MinIO.
- `apps/datasets/models.py` - `DatasetAsset`, upload paths, cleanup retry rows,
  and post-delete file cleanup.
- `apps/datasets/services.py` - image decoding, thumbnail generation, asset ref
  parsing, and image-column validation helpers.
- `apps/api/services.py` - image attachment, asset serialization, private and
  public content URLs, and rollback cleanup after failed storage writes.
- `apps/api/views.py` - authenticated asset metadata/content endpoints.
- `apps/datasets/views.py` and public preview templates - browser asset access
  for public previews.
- `apps/datasets/tests/test_csv_datasets.py` and
  `apps/datasets/tests/test_public_previews.py` - image asset, cleanup, and
  public preview coverage.

## Commands

```bash
make test -- apps/datasets/tests/test_csv_datasets.py -k "image or asset" -q
make test -- apps/datasets/tests/test_public_previews.py -k asset -q
make lint-python
```

When storage settings change, add an import/settings smoke check:

```bash
uv run python -c "import rowset.settings; import rowset.storages"
```

## Storage Rules

- Dataset assets use the `dataset_assets` storage alias, not the default public
  media storage.
- Local development without an S3 endpoint stores private files under
  `PRIVATE_MEDIA_ROOT`.
- S3-compatible storage requires endpoint, bucket, access key, and secret key at
  settings import time.
- Image cells store opaque `asset:{key}` references; row writes should not store
  raw image bytes directly.
- Public preview URLs are emitted only when the dataset preview is enabled and
  not password protected.

## Footguns

- Do not log raw image bytes, full private file contents, API keys, or storage
  credentials.
- Failed image writes must queue retryable cleanup rows instead of silently
  losing orphaned files.
- Deleting or replacing an asset should preserve row consistency and record
  cleanup failures through `DatasetAssetFileDeletion`.
- Do not expose private column descriptions or private referenced target metadata
  through public preview asset responses.
- Keep tests fakeable. Unit tests should not require real S3, MinIO, or external
  image hosting.
