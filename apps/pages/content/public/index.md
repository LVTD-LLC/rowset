# Rowset: one backend for AI agent workflows

Rowset is an MCP database and dataset API for AI agents. It gives agents reliable,
searchable structured data without requiring you to build a separate backend for every workflow.

## What agents can do

- Store typed, indexed rows with stable business keys or generated `rowset_id` values.
- Find a known row exactly or search by meaning with semantic search.
- Connect through hosted MCP, REST, or the Rowset CLI.
- Export snapshots as CSV, JSONL, XLSX, SQLite, or Parquet.
- Share an optional read-only public preview when people need browser access.

Datasets are private by default. Authenticated agent access uses a bearer API key; public previews
are an explicit, read-only sharing option rather than an authentication method.

## Start in three steps

1. [Create an account]({{ signup_url }}) and copy the Rowset setup prompt.
2. Give that prompt to a trusted agent so it can connect to hosted MCP.
3. Describe the workflow. The agent can create the dataset, choose a schema and stable index, and
   manage its rows.

Start with [the quickstart]({{ site_url }}/docs/quickstart) or explore
[Rowset use cases]({{ site_url }}/use-cases).

The full product is available in a 7-day trial. [See pricing]({{ site_url }}/pricing).
