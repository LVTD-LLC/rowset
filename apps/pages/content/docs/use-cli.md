---
title: Use Rowset from the CLI
description: Configure the Rowset CLI and verify API access.
keywords: Rowset CLI, ROWSET_API_BASE, self-hosted Rowset, command line, REST API
---

# Use Rowset from the CLI

Use the `rowset` CLI to work with datasets, rows, projects, relationships,
schema, assets, previews, and exports from a terminal. The CLI calls the same
authenticated REST API available to agents and applications.

## Before you begin

You need a Rowset account and an API key. Create the key on the Rowset instance
you intend to use.

## Install the CLI

Install the latest published release:

```bash
curl -fsSL https://github.com/LVTD-LLC/rowset/releases/latest/download/install-rowset-cli.sh | sh
```

Verify the installation:

```bash
rowset --version
```

## Connect to your Rowset instance

Store the API key privately:

```bash
export ROWSET_API_KEY="YOUR_ROWSET_API_KEY"
rowset user info
```

The CLI uses `https://rowset.lvtd.dev/api/` by default.

If you want to connect to a self-hosted instance, pass the REST API base as a
global option before the command:

```bash
rowset --api-base "https://rowset.example.com/api/" user info
```

To use the same self-hosted instance for every command, set `ROWSET_API_BASE`
instead:

```bash
export ROWSET_API_BASE="https://rowset.example.com/api/"
rowset user info
```

Use the public base URL you expose for the instance, including the `/api/`
path. The API key must come from that instance.

## Verify access

Run:

```bash
rowset user info
rowset capabilities
```

`rowset user info` returns safe account details for the authenticated user.
`rowset capabilities` returns the feature groups supported by the connected
instance. An authentication error usually means the API key and API base came
from different Rowset instances, or the key is missing from the environment.

## Run common commands

Discover datasets before creating a duplicate:

```bash
rowset dataset list
rowset dataset search "customer feedback"
```

Inspect a dataset before changing its rows:

```bash
rowset dataset get "{dataset_key}"
rowset row list "{dataset_key}"
```

Export a snapshot:

```bash
rowset export "{dataset_key}" csv --output dataset.csv
```

Run `rowset --help` for all command groups and global configuration options.
Use the [API overview](/docs/api-overview) for authentication details or
[Connect over MCP](/docs/connect-mcp) when an agent can discover Rowset tools
directly.
