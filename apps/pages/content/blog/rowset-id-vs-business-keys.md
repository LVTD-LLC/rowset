---
title: "Rowset rowset_id vs business keys: which should agents use?"
description: "Use a business key when the workflow already has a stable identifier; use Rowset's generated rowset_id when no natural key is safe."
published_at: 2026-07-08
author: Rasul Kireev
keywords:
  - Rowset rowset_id
  - business key
  - agent-managed rows
  - dataset index column
topics:
  - datasets
  - row identity
  - agent workflows
canonical_url: https://rowset.lvtd.dev/blog/rowset-id-vs-business-keys
image: /static/vendors/images/logo.png
image_alt: Rowset logo
robots: index, follow
---

Use a business key when the agent, user, and source system already share a
stable identifier such as `sku`, `task_id`, `slug`, `email`, or `external_id`.
Use Rowset's generated `rowset_id` when the source has no trustworthy natural
identifier, when candidate identifiers are optional or duplicated, or when the
dataset is still exploratory.

The choice is not cosmetic. In Rowset, the index column is the value an agent
uses for by-index reads, updates, image attachment, and relationship lookup
through [hosted MCP access](/docs/connect-mcp/) or the [Dataset
API](/docs/dataset-api/). The wrong choice turns a simple row patch into a
search problem. The right choice gives the agent one clear answer to "which row
did the user mean?"

## The short rule

Choose the identifier that will still be correct when the agent returns next
week.

If the workflow already has a durable business key, use it as `index_column`.
For a product catalog, that might be `sku`. For a content queue, it might be
`slug`. For an agent task board, it might be `task_id`. For a CRM, it might be
`person_id` or `email`, depending on how stable email is in that workflow.

If the workflow does not have that kind of key, omit `index_column` when
creating the dataset. Rowset will add a generated `rowset_id` column so the
dataset can still be read and updated safely. In Rowset, generated index columns
are managed identity: generated values are assigned by Rowset, generated index
columns cannot be renamed, and generated index values should not be rewritten as
business data.

This is close to a database primary-key decision, but with an agent-specific
twist. PostgreSQL describes a primary key as a column or group of columns that
uniquely identifies rows and rejects null values
([PostgreSQL constraints docs, 2026](https://www.postgresql.org/docs/current/ddl-constraints.html)).
PostgreSQL also supports identity columns that generate values automatically
from a sequence
([PostgreSQL identity columns docs, 2026](https://www.postgresql.org/docs/current/ddl-identity-columns.html)).
Rowset is not asking you to design a full relational schema. It is asking you
to choose the safest row handle for trusted agents.

## Business keys are best when they are already real

A business key is an identifier the workflow already uses. It is not invented
only because Rowset needs an index. It is the value a user, source file, API
payload, ticket, or downstream system naturally carries.

Good business keys have four traits:

1. They are unique inside the dataset.
2. They are required for every row the agent will update.
3. They survive normal workflow changes.
4. They are recognizable to the agent or source system later.

That last point matters for agents. An internal database id can be technically
unique but useless if the user never says it and the source file never exports
it. A row identity that only exists inside one hidden system forces the agent to
list, search, or guess before every update.

Use a business key when the instruction naturally sounds like this:

```text
Update product SKU-104.
Move TASK-812 to review.
Mark /blog/mcp-vs-rest-ai-agents as published.
Attach the receipt to invoice INV-2026-040.
```

In those cases, `sku`, `task_id`, `slug`, and `invoice_id` are not merely
database fields. They are the handles the workflow already trusts.

## Generated `rowset_id` is best when identity is still uncertain

Let Rowset generate `rowset_id` when no candidate business key passes the
stability test. This is common with imported notes, messy research lists,
one-off review queues, source material extracted from documents, or early
datasets where the workflow is not yet proven.

Generated `rowset_id` is especially useful when:

- names can collide or be rewritten
- emails are missing, shared, or likely to change
- titles are draft text, not identity
- source URLs can redirect or represent multiple rows
- rows come from unstructured material with no durable id
- the dataset needs safe row operations before the team knows its final shape

The tradeoff is scope. `rowset_id` is stable inside Rowset, but it has no
meaning to an upstream system unless you export it and keep it with the source.
That is fine for Rowset-native workflows. It is weaker when another system needs
to send updates back by a value it already knows.

Use generated identity when the safest instruction is:

```text
This dataset has no reliable source id. Use Rowset's generated rowset_id for
row lookup. Do not infer identity from title, status, owner, or summary.
```

That instruction is better than pretending a weak natural key is strong.

## Decision table

| Situation | Use a business key | Use generated `rowset_id` |
|---|---|---|
| Product catalog with stable SKUs | Yes, use `sku` | Only if SKUs are missing or duplicated |
| Content pipeline with permanent slugs | Yes, use `slug` | Use while ideas do not have slugs yet |
| Agent task board | Yes, use `task_id` or issue key | Use for scratch task lists without IDs |
| CRM contacts | Use `person_id` or `contact_id`; use `email` only if stable | Use when emails are optional, shared, or mutable |
| Research notes | Use `citation_key`, `source_id`, or `note_id` if real | Commonly a good fit |
| Imported PDF/table extraction | Rarely, unless source rows include IDs | Usually safest |
| Relationship target dataset | Prefer stable business key | Avoid if external rows need to reference it |

The pattern is simple: use the identifier the workflow can name again. If the
workflow cannot name one, let Rowset create one.

## Why agents make the tradeoff sharper

A human can often recover from weak identity. They notice two similar rows, ask
a teammate, open the source document, or recognize the right record from context.
An agent only has the context it can inspect.

MCP helps because tools expose names, descriptions, and input schemas that a
model can use before it acts
([MCP tools specification, 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)).
Rowset adds dataset context on top of that: headers, index column, instructions,
metadata, column schema, relationships, and rows.

But the index value is still the point where context becomes action. If the
agent is asked to update a row by `TASK-812`, it needs exactly one row behind
that value. If the dataset index is `title`, the update may fail later when the
title changes. If the index is `owner`, the update is not an identity operation
at all. It is a guess.

This is why [choosing an index column for agent-managed
rows](/blog/choose-index-column-agent-rows) should happen before production
rows accumulate. Row identity becomes part of the operating contract.

## How this affects retries and duplicate prevention

Row identity and idempotency are not the same thing, but they support the same
kind of safety. Stripe's API docs describe idempotency keys as a way to retry a
request without accidentally performing the same operation twice
([Stripe API docs](https://docs.stripe.com/api/idempotent_requests)).

For agent-managed rows, a stable index gives you a similar practical benefit at
the dataset level. If an agent loses context after creating or updating a row,
it can come back to the same `sku`, `slug`, `task_id`, or `rowset_id` instead of
creating a duplicate that merely looks similar.

This does not remove the need for careful API behavior, validation, or review.
It does make the recovery path clearer:

1. Inspect the dataset with `get_dataset`.
2. Confirm the index column.
3. Look up the row by index value.
4. Patch the existing row instead of creating a second one.

That pattern is easier to execute when the index is a real workflow handle.

## How this affects exports and imports

Use a business key when rows need to round-trip through another system that
already knows the key. If a product catalog comes from an ecommerce backend,
`sku` or `product_id` should usually travel with every export and import. If a
content queue connects to a repo, `slug` is usually the thing both systems can
name.

Use generated `rowset_id` when Rowset is the first system giving the row a safe
identity. If you later export those rows to CSV, JSONL, SQLite, or another
tool, keep the `rowset_id` column in the exported data if you expect future
updates to come back to Rowset.

The dangerous middle ground is stripping identity during export. A dataset can
start with generated `rowset_id`, leave Rowset, get edited elsewhere, and come
back without the generated values. At that point the agent has to match rows
from content, which is weaker than lookup.

If you use generated identity, treat it as part of the row data whenever the
workflow leaves Rowset.

## How this affects relationships

Relationships make the decision more durable. Rowset relationships use target
row index values. One dataset can store another dataset's row index value, and
Rowset can resolve that link through MCP or REST.

For example:

- `People.person_id` identifies people.
- `Messages.message_id` identifies messages.
- `Messages.person_id` points back to the person.

With relationship integrity enabled, Rowset can reject non-blank relationship
values that do not match the target dataset's index. That is useful only if the
target index is stable enough to act like a real reference.

Generated `rowset_id` can work for relationships inside Rowset, especially when
Rowset owns both datasets. A business key is better when another system or human
will create the relationship value outside Rowset. A message imported from a
CRM is more likely to carry `person_id` than an opaque Rowset-generated value.

## A safe migration pattern

Do not force the perfect index on day one. Use a two-stage pattern when identity
is uncertain:

1. Start with generated `rowset_id`.
2. Keep candidate business identifiers as normal columns.
3. Add column descriptions explaining their current reliability.
4. Watch which value agents and source systems actually use.
5. Move to a business key only when it is required, stable, unique, and present.

This keeps early datasets usable without turning a weak field into permanent
identity too soon.

For example, a research dataset might start with:

```json
{
  "headers": ["title", "source_url", "summary"],
  "rows": [
    {
      "title": "MCP tool schema note",
      "source_url": "https://modelcontextprotocol.io/specification/2025-06-18/server/tools",
      "summary": "Tools expose names, descriptions, and input schemas."
    }
  ]
}
```

If `index_column` is omitted, Rowset adds `rowset_id`. Later, if the workflow
settles on a real `citation_key`, make that explicit for future datasets instead
of retroactively pretending `source_url` was always safe.

## What to put in dataset instructions

The index decision should be visible to future agents. Put it in dataset
instructions, not only in the setup chat.

For a business key:

```text
Use sku as the stable row identity. Before updating rows, call get_dataset,
confirm the index_column is sku, then update by index_value. Do not use name,
price, or category as identity because they can change.
```

For generated identity:

```text
This dataset uses Rowset-generated rowset_id as the stable row identity. Preserve
rowset_id in exports and imports. Do not change generated index values. If a
future source system provides stable IDs, add them as a normal column first and
review before changing the workflow.
```

That instruction gives the agent a local rule it can inspect before mutating
rows. Pair it with semantic column descriptions in [dataset schema
design](/docs/design-schema/) and use [dataset instructions for AI
agents](/blog/structure-dataset-instructions-ai-agents) when the workflow rules
need more detail.

## Product-led takeaway

Rowset's value is not that every dataset has the same kind of id. It is that
trusted agents get an explicit, inspectable row identity before they act.

Use business keys when they are real. Use `rowset_id` when identity would
otherwise be guessed. Keep the decision visible in dataset instructions. Preserve
the index through exports. And before giving an agent write access, make sure it
can call `get_dataset`, see the current index column, and patch rows through
the [Dataset API](/docs/dataset-api/) or [MCP tools](/docs/mcp-tools/).

## FAQ

### Is `rowset_id` the same as a database primary key?

No. `rowset_id` is Rowset's generated dataset index column. It gives a row a
stable Rowset-managed lookup value, but it is not a general database schema
primitive or a promise that external systems already know the value.

### Should agents always use business keys?

No. Agents should use business keys only when those keys are stable, unique,
required, and available to the future workflow. If the key is uncertain, a
generated `rowset_id` is safer than a misleading natural key.

### Can generated `rowset_id` values be edited?

Treat generated `rowset_id` values as Rowset-managed identity. Rowset can accept
unchanged generated values in full-row updates, but agents should not rewrite
them as business data.

### What if a better business key appears later?

Add the new key as a normal column first, describe it, and verify that it is
unique and present. Change the workflow only after agents and source systems can
reliably use that value.

### Which index is better for relationships?

Use the target dataset's stable business key when other systems or humans will
write relationship values. Generated `rowset_id` is fine for Rowset-owned
relationships when those generated values are preserved wherever related rows
are created or imported.
