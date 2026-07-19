---
name: rowset-use-cases
description: Use when a user asks how to use Rowset for a specific workflow, wants examples, or needs a recommended dataset shape for an agent-managed CRM, task board, feedback tracker, content pipeline, catalog, or QA tracker.
---

# Rowset Use Cases

Use this skill to design practical Rowset dataset shapes through the MCP, CLI,
or REST interface selected by the user. Treat the patterns below as examples,
verify them against the live capability guide and current interface docs, and
keep public previews for explicitly requested read-only human sharing.

Before creating or changing datasets:

1. Do not load capabilities or list datasets merely because a session started.
   For unfamiliar workflows or troubleshooting, load the capability topic index
   through the selected interface, then request only relevant topics with use
   cases included. Do not retrieve the full guide unless the workflow needs it.
2. When the user supplies a dataset key or URL, inspect that dataset directly.
   MCP `get_dataset` accepts either value. For CLI or REST, extract the dataset
   key from the URL before using `rowset dataset get` or
   `/api/datasets/{dataset_key}`. Otherwise, search only the relevant datasets
   or projects with an explicit limit of 3, select one, and inspect its full
   context before creating anything new.
3. Pick an explicit index column, or let Rowset generate `rowset_id` when no
   reliable business key exists.
4. Add dataset instructions, JSON metadata, column descriptions, and choice
   columns when the agent needs durable operating context.
5. Use relationships when one dataset stores another dataset row's index value.

## Personal CRM

Use when the user wants agents to remember people, companies, conversations,
and follow-ups.

Starter shape:

- `People` dataset indexed by `email` or `person_id`.
- `Companies` dataset indexed by `company_id`.
- `Interactions` or `Messages` dataset indexed by `message_id`.
- Relationship from `Messages.person_id` to `People.person_id`.

Useful context:

- People instructions: "Use email as the stable identity. Do not rewrite names
  from guesses."
- Messages instructions: "Create one row per meaningful interaction. Link to a
  person when the identity is known."
- Choice columns for relationship stage, follow-up status, or source.

## Agent Task Board

Use when the user wants agents to track planned work, blockers, owners, and
completion state.

Starter shape:

- `Tasks` dataset indexed by `task_id`.
- Choice column `status` with values such as `todo`, `blocked`, `doing`, `done`.
- Optional `Projects` Rowset project for the initiative.

Useful context:

- Dataset instructions define status transitions and when the agent may close a
  task.
- Metadata can hold status order, default priority, or review rules.
- Use row-by-index updates when `task_id` is known.

## Feedback Triage

Use when the user wants to capture customer feedback, classify it, and track
follow-up.

Starter shape:

- `Feedback` dataset indexed by `feedback_id`.
- `Customers` dataset indexed by `customer_id` or `email`.
- Relationship from `Feedback.customer_id` to `Customers`.

Useful context:

- Choice columns for `status`, `sentiment`, `source`, and `priority`.
- Metadata for triage policy, escalation rules, or target response time.
- Public preview only if the user wants a read-only summary link.

## Content Pipeline

Use when the user wants to manage articles, landing pages, newsletters, or
social posts.

Starter shape:

- `Content` dataset indexed by `slug`.
- Choice column `stage` with values such as `idea`, `draft`, `review`,
  `scheduled`, `published`.
- Project metadata linking to docs, repositories, editorial calendars, or source
  threads.

Useful context:

- Column descriptions for audience, channel, due date, owner, and canonical URL.
- Use exports when another tool needs a full content snapshot.

## Product Or Inventory Catalog

Use when the user wants a structured catalog that agents can update and humans
can inspect.

Starter shape:

- `Products` dataset indexed by `sku`.
- Semantic column types for `price`, `product_url`, `image_url`, and
  `updated_at`.
- Optional public preview for read-only sharing.

Useful context:

- Dataset instructions define currency, supplier naming, and retirement rules.
- Choice columns for lifecycle state such as `draft`, `active`, `retired`.

## Bug Or QA Tracker

Use when the user wants agents to track issues, repro details, severity, and
customer impact.

Starter shape:

- `Issues` dataset indexed by `issue_id`.
- Choice columns for `status` and `severity`.
- Optional `Releases`, `Customers`, or `Components` datasets with relationships
  from `Issues`.

Useful context:

- Instructions define when an issue can move to fixed or verified.
- Metadata can store severity definitions, owner rules, and triage schedule.

## Pattern Checklist

For any new use case, choose:

- Dataset names and one stable index per dataset.
- Which values should be choice columns.
- Which column descriptions prevent agent guessing.
- Which relationships should enforce row integrity.
- Which project metadata should store source links or workflow context.
- Which actions are destructive and require explicit user confirmation.
