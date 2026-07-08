---
title: Attach images
description: Store private image assets in Rowset image columns and expose authenticated or preview-safe URLs.
keywords: Rowset image columns, dataset image assets, attach image to row
---

# Attach images

Use image columns when a dataset row needs a private visual asset, such as a
product photo, receipt, screenshot, generated image, or catalog reference image.

## Create an image column

Create the dataset or add a column with type `image`:

```json
{
  "photo": {
    "type": "image",
    "description": "Primary product photo"
  }
}
```

Leave image cells blank during normal row writes. Rowset writes an opaque
`asset:{key}` reference after an image is attached.

## Attach an image

MCP:

```text
attach_image_to_dataset_row
```

REST:

```http
POST {{ api_base_url }}/datasets/{dataset_key}/rows/{row_id}/image
POST {{ api_base_url }}/datasets/{dataset_key}/rows/by-index/image?index_value=SKU-001
```

The target row must exist first. For MCP, the agent must read local image bytes
itself and pass base64 or a data URI. The hosted MCP server cannot read a local
file path from the agent machine.

Supported input formats are JPEG, PNG, and WebP.

## Read asset metadata

MCP:

```text
get_dataset_image_asset
```

REST:

```http
GET {{ api_base_url }}/datasets/{dataset_key}/assets/{asset_key}
GET {{ api_base_url }}/datasets/{dataset_key}/assets/{asset_key}/content
```

Asset metadata includes content URL, thumbnail URL, content type, byte size,
dimensions, checksum, and public preview URLs when the dataset preview is
enabled without password protection.

Rowset normalizes image bytes before storage. `byte_size` and `checksum`
describe the stored Rowset asset, not necessarily the original local file.

## Public previews and exports

Images appear in authenticated dataset views and public previews when sharing is
enabled. File exports include the stable `asset:{key}` cell reference rather
than embedding binary image data.

## Audio follows the same pattern

For private audio files, create a column with type `audio` and use
`attach_audio_to_dataset_row` or the REST `/audio` row endpoint. Rowset accepts
MP3, WAV, M4A, AAC, Ogg, FLAC, and WebM audio bytes, stores the file privately,
and writes the same `asset:{key}` cell reference.
