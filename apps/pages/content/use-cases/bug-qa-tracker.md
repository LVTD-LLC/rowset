---
title: Bug and QA tracker
description: Use Rowset as an agent-friendly bug and QA tracker for issues, severity, repro notes, releases, fixes, and customer impact.
keywords: bug tracker, QA tracker, Rowset use case
---

# Bug and QA tracker

Use Rowset when agents run QA, file bugs, and summarize release risk but do not
need a full issue tracker for every temporary test finding.

## Starter shape

Create an `issues` dataset indexed by `issue_id`.

| issue_id | title | severity | status | component | repro_notes | affected_version | customer_impact |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ISS-442 | Export timeout on large dataset | high | open | exports | 50k-row CSV times out | 2026.07 | Blocks backup |
| ISS-451 | Preview password copy unclear | medium | review | previews | Settings label is ambiguous | 2026.07 | Confuses sharing |
| ISS-463 | Settings layout overflow | low | fixed | settings | Long key names overflow | 2026.07 | Cosmetic |

## Agent jobs

- Create issues with reproduction notes and affected version.
- Update severity, owner, release, and fix status.
- Link bugs to customers, releases, or components.
- Export triage snapshots before release review.

## Workflow rules

Define severity meanings and the evidence required before a bug can move to
`fixed`. Keep reproduction notes specific enough for another agent or engineer
to replay without scraping chat history.

## Connect it

Use [MCP access](/docs/connect-mcp) when agents create or update issues. Use
the [Dataset API](/docs/dataset-api) when automated checks write failures into
the tracker.
