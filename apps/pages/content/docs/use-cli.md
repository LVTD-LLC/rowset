---
title: Use Rowset from the CLI
description: Configure the Rowset CLI for Rowset Cloud or a self-hosted instance and verify API access.
keywords: Rowset CLI, ROWSET_API_BASE, self-hosted Rowset, command line, REST API
---

# Use Rowset from the CLI

Use the `rowset` CLI to work with datasets, rows, projects, relationships,
schema, assets, previews, and exports from a terminal. The CLI calls the same
authenticated REST API available to agents and applications.

## Before you begin

You need a Rowset account and an API key. Create the key on the Rowset instance
you intend to use. A key created on Rowset Cloud cannot authenticate with a
self-hosted instance, and a self-hosted key cannot authenticate with Rowset
Cloud.

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

The REST API base for the Rowset instance serving these docs is:

```text
{{ api_base_url }}/
```

Store the API key privately and set the API base explicitly:

```bash
export ROWSET_API_KEY="YOUR_ROWSET_API_KEY"
export ROWSET_API_BASE="{{ api_base_url }}/"
rowset user info
```

Setting `ROWSET_API_BASE` makes the target instance explicit and works for both
Rowset Cloud and self-hosted deployments. The CLI defaults to the Rowset Cloud
API when `ROWSET_API_BASE` is unset.

For a one-off command, pass the API base as a global option before the command:

```bash
rowset --api-base "{{ api_base_url }}/" user info
```

For self-hosted Rowset, configure the deployment's `SITE_URL` to its public
origin. Rowset then displays the corresponding REST base ending in `/api/`.
Use the URL shown by that instance rather than the Rowset Cloud URL.

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
