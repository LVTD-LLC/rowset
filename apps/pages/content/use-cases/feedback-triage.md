---
title: Feedback triage
description: Use Rowset to collect, classify, dedupe, and follow up on customer feedback with private MCP and REST access.
keywords: feedback triage, customer feedback dataset, Rowset use case
---

# Feedback triage

Use Rowset when feedback arrives from support, calls, emails, community posts,
and product notes, but an agent needs one structured place to classify it.

## Starter shape

Create a `feedback` dataset indexed by `feedback_id`.

| feedback_id | customer | source | theme | severity | duplicate_of | status | next_action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FB-203 | Northstar Labs | support | billing | medium |  | open | Ask for invoice format |
| FB-219 | Acme | call | mcp | high |  | planned | Scope team API keys |
| FB-224 | Studio Dev | chat | import | low | FB-203 | closed | Link to billing thread |

## Agent jobs

- Dedupe related requests into a consistent theme.
- Attach customer, account, and source context.
- Count repeated signals without losing the original request.
- Share a read-only preview when stakeholders need a board.

## Workflow rules

Tell the agent how to pick themes, how to set severity, and when to mark
feedback as duplicate. Use `duplicate_of` to preserve individual customer
evidence while keeping roadmap discussion focused.

## Connect it

Use [MCP access](/docs/connect-mcp/) for trusted agent triage. Use the
[Dataset API](/docs/dataset-api/) when a support or feedback script needs to
write rows directly.
