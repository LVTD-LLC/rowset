---
title: How to model relationships between agent-managed datasets
description: Split Rowset datasets when agents need stable cross-row links, then connect them with index values, relationship enforcement, and clear instructions.
published_at: 2026-07-13
author: Rasul Kireev
keywords:
  - agent dataset relationships
  - linked datasets for AI agents
  - Rowset relationships
  - agent-managed datasets
topics:
  - datasets
  - relationships
  - agent workflows
canonical_url: https://rowset.lvtd.dev/blog/relationship-modeling-agent-datasets
image: /static/vendors/images/logo.png
image_alt: Rowset logo
robots: index, follow
---

Model relationships between agent-managed datasets when one row needs to point
at another row that has its own lifecycle. Keep the target dataset indexed by a
stable value, store that value in the source dataset, and tell the agent when to
resolve the relationship before it writes.

For Rowset, the practical pattern is simple: split datasets by real workflow
entities, use stable index columns as the link values, and add relationship
rules only where they reduce ambiguity for the agent. Do not split a dataset
just because a relational database would have another table.

## The short rule

Create a separate dataset when the thing being referenced can be created,
updated, reviewed, or reused on its own.

Keep the data in one dataset when the fields only describe the same row. A
`customer_email` column on a feedback item is usually just context. A `person_id`
that points to a separate People dataset is a relationship, because the person
has their own history, messages, owner, and follow-up rules.

This distinction matters more for agents than for humans. A human can often
scan a few rows and infer the intended link. An agent needs the relationship to
be explicit enough to inspect, resolve, and update without guessing.

In Rowset, relationship links use index values. The target dataset needs a
stable index such as `person_id`, `sku`, `task_id`, `ticket_id`, or `slug`. The
source dataset stores that target index value in a normal column. The
relationship definition says, in effect: `Messages.person_id` points to
`People.person_id`.

That is close to the foreign-key idea in relational databases. PostgreSQL's
current docs describe foreign keys as a way to keep references valid between
tables and note that using them improves data quality
([PostgreSQL, 2026](https://www.postgresql.org/docs/current/tutorial-fk.html)).
Rowset is not asking an agent to design a full SQL schema, but the safety goal
is the same: a link should point to something real.

## Use one dataset until the relationship pays for itself

The easiest mistake is over-modeling. A dataset with five tightly related
fields is often safer than three small datasets the agent has to join mentally.

Use one dataset when:

- the row is updated as a unit
- the referenced value is only descriptive context
- the agent never needs to list, search, or update the referenced thing
- a relationship would add setup work but no safer action

For example, a content queue can start with one dataset:

| slug | title | stage | owner | canonical_url |
|---|---|---|---|---|
| agent-datasets | What is an agent-managed dataset? | published | Rasul | /blog/agent-managed-datasets |

The `owner` field does not need to be a People dataset unless the owner itself
has workflow data the agent should manage. If the only question is "who owns
this draft?", a text column is enough.

This is the product-led SEO reason Rowset's relationship guidance starts from
the user job, not the schema diagram. The useful surface is not "more tables."
It is a dataset shape an agent can operate on reliably through [hosted MCP
access](/docs/connect-mcp/) or the [Dataset API](/docs/dataset-api/).

## Split datasets when rows need independent identity

Split one dataset into related datasets when a row starts carrying two kinds of
identity.

Good split signals:

1. **Independent lifecycle.** A person, product, task, source, or content item
   can be updated without updating the row that references it.
2. **Repeated references.** Many rows point at the same thing.
3. **Different instructions.** The target row has its own safe-update rules.
4. **Review needs.** Humans need to inspect the target entity separately.
5. **Agent lookup.** The agent often needs to resolve the link before writing.

For a personal CRM, keep `People` and `Messages` separate once messages become
more than a note field:

| Dataset | Index | Important fields |
|---|---|---|
| People | `person_id` | name, email, company, relationship_status |
| Messages | `message_id` | person_id, channel, sent_at, summary, follow_up_needed |

`Messages.person_id` is the relationship column. The agent can inspect a
message, resolve the related person, and update the person only when the user
actually asked for that outcome.

For a product catalog, use `Products.sku` as the target index and let price
checks, supplier notes, or inventory observations point back to it. For a bug
or QA tracker, use `Issues.issue_key` as the target index and let test runs,
screenshots, or reproduction notes reference that issue.

## Pick relationship keys before writing instructions

Relationship modeling starts with index choices. If the target dataset has a
weak index, every linked dataset inherits that weakness.

Use the same checks from the [index-column guide](/blog/choose-index-column-agent-rows):
the target value should be unique, required, stable, recognizable to the agent,
and present in exports or upstream systems. If the target value can change
during normal work, do not use it as the relationship handle.

Bad relationship keys usually look convenient:

- `name`, because names change and collide
- `title`, because titles are edited
- `status`, because status is the thing changing
- `email`, when the workflow allows shared inboxes or multiple addresses
- internal ids the agent never sees in source material

Better keys are boring: `person_id`, `sku`, `ticket_id`, `message_id`,
`source_url`, `slug`, or Rowset's generated `rowset_id` when no natural key is
safe. The companion guide to [Rowset `rowset_id` vs business
keys](/blog/rowset-id-vs-business-keys) explains that tradeoff in more detail.

## Tell the agent how to resolve the link

A relationship is only useful if the agent knows when to follow it.

Put the operating rule in dataset instructions. Put parseable values in
metadata when another tool may need them later. For a message dataset, the
instructions might say:

```text
This dataset stores messages linked to People.
Use message_id as the row identity. The person_id column points to People.person_id.
Before updating person-level fields, resolve the relationship and inspect the
People row. Do not create a new People row until search confirms no matching
person exists.
```

That instruction does three things:

- names the row identity for the current dataset
- names the relationship target
- defines the stop condition before creating duplicate people

The [dataset instructions guide](/blog/structure-dataset-instructions-ai-agents)
uses the same principle: durable workflow rules should live with the dataset,
not only in the current chat. The agent should call `get_dataset` before row
operations so it sees the index column, schema, instructions, and relationship
summaries.

This matches how MCP is meant to be used. The current MCP tools specification
says tools are exposed with names and metadata describing their schemas so a
model can invoke external systems safely
([Model Context Protocol, 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)).
Rowset adds dataset-specific context on top of that tool layer.

## Use enforcement for links the agent should not invent

In Rowset, relationships can be enforced. With enforcement enabled, row writes
fail when a non-blank source value does not match an existing target row index.
Blank values are still allowed, which is useful when the relationship is not
known yet.

Use enforcement when:

- a source row should never point at a missing target
- creating a target row requires deliberate review
- downstream automation assumes the link is valid
- duplicate targets would create real cleanup work

Leave enforcement off, or delay it, when:

- the agent is still importing messy source material
- the workflow allows temporary unmatched rows
- the target dataset is being built in phases
- the relationship is useful context but not a hard rule

This is a data-quality choice, not a purity test. Enforcement is valuable when
it turns a silent agent mistake into an explicit error the agent can report.
It is harmful when it blocks legitimate work before the dataset is ready.

## Relationship examples by workflow

### Personal CRM

Use `People.person_id` as the target and link messages, reminders, and meeting
notes to people.

| Source dataset | Source column | Target dataset | Target index |
|---|---|---|---|
| Messages | person_id | People | person_id |
| Follow-ups | person_id | People | person_id |

This lets the agent answer questions like "what did I last promise Priya?" by
searching messages and resolving the person row before updating the follow-up
state.

### Content pipeline

Use `Content.slug` as the target and link tasks, research notes, source checks,
and publication records back to the canonical piece.

| Source dataset | Source column | Target dataset | Target index |
|---|---|---|---|
| Research notes | slug | Content | slug |
| Review tasks | slug | Content | slug |

This pairs well with Rowset's [content pipeline use case](/use-cases/content-pipeline/).
The content row owns the current stage. Related rows hold evidence and review
work without bloating the main queue.

### Product inventory

Use `Products.sku` as the target and link supplier observations, price checks,
or image assets back to products.

| Source dataset | Source column | Target dataset | Target index |
|---|---|---|---|
| Supplier checks | sku | Products | sku |
| Image review | sku | Products | sku |

The agent can update a product row by `sku`, attach review evidence to a
separate dataset, and keep the product identity stable even when names or
prices change.

### Feedback triage

Use `Feedback.feedback_id` as the target and link duplicate reports, feature
requests, or release notes to the original item.

If two feedback rows may be duplicates, avoid rewriting the original evidence.
Store `duplicate_of` as a relationship-style field and tell the agent to ask
before merging or closing rows.

## Common mistakes

The most common mistake is making relationships too human. A note like "this
belongs to Sarah's project" may be clear to you, but it is weak data for an
agent. Prefer a project key, person id, source URL, ticket id, or another value
the agent can resolve.

Other mistakes:

- linking by display names instead of stable ids
- splitting datasets before the workflow needs separate lifecycles
- leaving relationship rules only in the chat prompt
- enforcing links during a messy import before target rows exist
- letting an agent create target rows without duplicate checks
- hiding source evidence in the relationship instead of storing it in a row
- treating public previews as the agent's relationship lookup path

Public previews are for human review. Agents that need to inspect or mutate
related datasets should use private MCP or REST access with the right key.

## A quick checklist

Before giving an agent write access to related datasets, check:

1. Each dataset has one clear job.
2. Every target dataset has a stable index column.
3. Source columns store the target index value, not a display label.
4. Dataset instructions say when to resolve the relationship.
5. The agent is told to inspect `get_dataset` before updates.
6. Enforcement is enabled only where missing targets should block writes.
7. Humans have a review path for uncertain matches.
8. The main dataset still reads clearly without unnecessary splits.

If those checks pass, the relationship model is probably useful. If they fail,
simplify the dataset or strengthen the index before adding more links.

## FAQ

### Are Rowset relationships the same as SQL foreign keys?

No. They serve a similar safety purpose, but Rowset relationships are a
dataset-level agent workflow feature. They connect a source column to a target
dataset's index value so MCP and REST clients can inspect and resolve links.

### Should every repeated value become a relationship?

No. Repetition alone is not enough. Create a relationship when the repeated
thing has its own lifecycle, instructions, review path, or agent lookup need.
Otherwise, keep it as a normal column.

### Can an agent create missing target rows automatically?

Only when the workflow explicitly allows it. For most production datasets, tell
the agent to search first, ask when uncertain, and create the target row only
when the user has requested it or the instructions permit it.

### Should I use reference columns or relationships?

Use reference columns when a cell should point to a Rowset object such as a
dataset or project. Use relationships when a cell points to a row inside
another dataset. The [Link datasets docs](/docs/link-datasets/) describe both
patterns.

### What is the safest default for a new relationship?

Start with a stable target index and clear instructions. Delay hard enforcement
until the target dataset is clean enough that missing links should be treated as
errors, not normal setup work.
