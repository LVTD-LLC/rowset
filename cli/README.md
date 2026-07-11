# Rowset CLI

`rowset` is a Go CLI for Rowset's authenticated REST API. Command groups mirror
the user-facing API and MCP operations: account checks, API keys, feedback,
projects, datasets, rows, relationships, schema changes, image/audio assets, public
previews, archives, restores, and exports.

The CLI sends bearer auth from an environment variable. Do not pass raw API keys
through shell history or commit them to config files.

## Setup

Install the latest published CLI:

```bash
curl -fsSL https://github.com/LVTD-LLC/rowset/releases/latest/download/install-rowset-cli.sh | sh
```

The installed command is `rowset`. It defaults to Rowset production:

```text
https://rowset.lvtd.dev/api/
```

Store your private Rowset API key and verify authentication:

```bash
export ROWSET_API_KEY="replace-with-your-copied-key"
rowset user info
```

Install a specific release:

```bash
curl -fsSL https://github.com/LVTD-LLC/rowset/releases/latest/download/install-rowset-cli.sh \
  | ROWSET_CLI_VERSION="2026.07.08-0" sh
```

For local development from source:

```bash
cd cli
go test ./...
go run ./cmd/rowset --help
```

Point the CLI at a non-production Rowset REST API base:

```bash
export ROWSET_API_BASE="http://localhost:8000/api/"
rowset user info
```

For a non-default key variable:

```bash
export ROWSET_PROD_API_KEY="replace-with-your-copied-key"
rowset --api-key-env ROWSET_PROD_API_KEY user info
```

## Examples

Verify authentication:

```bash
rowset user info
```

Inspect Rowset capability groups:

```bash
rowset capabilities
```

Create a dataset:

```bash
rowset dataset create \
  --name Products \
  --headers sku,name,price,status,tags \
  --index-column sku \
  --column-types '{"price":"currency","status":{"type":"choice","choices":["draft","active","retired"]},"tags":"tags"}' \
  --row '{"sku":"A-1","name":"Adapter","price":"19.99","status":"active","tags":"hardware, usb-c"}'
```

Inspect a dataset before row work:

```bash
rowset dataset get "{dataset_key}"
```

Patch a row by stable index value:

```bash
rowset row update-by-index "{dataset_key}" A-1 \
  --data '{"status":"retired"}'
```

Search across datasets:

```bash
rowset row search "renewal risks" \
  --filters '{"status":"Ready"}' \
  --sort rank \
  --limit 10
```

Export a snapshot:

```bash
rowset export "{dataset_key}" csv --output dataset.csv
```

Attach an image to an image column:

```bash
rowset asset attach "{dataset_key}" \
  --index-value A-1 \
  --column photo \
  --file ./adapter.png \
  --content-type image/png
```

Attach audio to an audio column:

```bash
rowset asset attach "{dataset_key}" \
  --asset-type audio \
  --row-id 7 \
  --column clip \
  --file ./interview.wav \
  --content-type audio/wav
```

Use the escape hatch for a REST path not yet represented by a friendly command:

```bash
rowset request PATCH /datasets/{dataset_key}/public-preview \
  --json '{"public_enabled":false}'
```

## Command Groups

- `capabilities`, `user info`, `feedback submit`, `api-key create`
- `project list|search|create|get|update|metadata|archive|section`
- `dataset list|search|archived|get|create|metadata|column-types|project|archive|restore`
- `preview update`
- `column add|rename|drop|reorder`
- `relationship list|create|resolve|delete`
- `row list|search|search-dataset|get|get-by-index|create|update|update-by-index|delete`
- `asset attach|get|content`
- `export DATASET_KEY csv|jsonl|xlsx|sqlite`
- `request METHOD PATH`

## Build

```bash
mkdir -p bin
go build -o bin/rowset ./cmd/rowset
```

From the repository root:

```bash
make cli-test
make cli-build
```
