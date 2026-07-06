---
title: Content pipeline
description: Use Rowset to manage article, landing page, newsletter, and programmatic SEO workflows as agent-editable datasets.
keywords: content pipeline, SEO workflow dataset, Rowset use case
---

# Content pipeline

Use Rowset when agents need to track content briefs, drafts, review state,
canonical URLs, and publishing evidence without forcing the workflow into a CMS.

## Starter shape

Create a `content_queue` dataset indexed by `slug`.

| slug | content_type | stage | owner | target_keyword | canonical_url | publish_date | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mcp-dataset-api | blog | review | Scribe | MCP dataset API |  |  | Needs examples |
| agent-crm-guide | use case | draft | Scribe | agent CRM | /use-cases/personal-crm/ |  | Outline approved |
| feedback-board | landing | idea | Beacon | feedback board |  |  | Use-case angle |

## Agent jobs

- Create briefs from research and customer notes.
- Move items through review and publish stages.
- Attach canonical URLs, owners, and completion evidence.
- Export the queue for editors, scripts, or downstream systems.

## Workflow rules

Define stages before agents start editing: `idea`, `brief`, `draft`, `review`,
`scheduled`, and `published` are enough for most small teams. Add instructions
for when agents can create drafts, when they must wait for approval, and where
published URLs should be recorded.

## Connect it

Use [MCP access](/docs/connect-mcp/) for agent planning and updates. Use the
[Dataset API](/docs/dataset-api/) when a publishing script needs a structured
queue.
