# Rowset: one backend for AI agent workflows

Rowset is the open-source, self-hostable backend for AI agent workflows. It gives agents private,
searchable structured data through MCP, REST, or CLI without requiring you to build another backend.

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
2. Let the agent recommend MCP, CLI, or REST, then choose which interface it should configure.
3. Describe the workflow. The agent can create the dataset, choose a schema and stable index, and
   manage its rows.

Start with [the quickstart]({{ site_url }}/docs/quickstart) or explore
[Rowset use cases]({{ site_url }}/use-cases).

The full product is available in a 7-day trial. [See pricing]({{ site_url }}/pricing).
