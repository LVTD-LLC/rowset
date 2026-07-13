---
title: Agent task board
description: Use Rowset as an agent task board with durable status, owner, priority, blocked-state, and handoff rows.
keywords: agent task board, AI task tracker, Rowset use case
---

# Agent task board

Use Rowset as a small task ledger when agent work needs durable state across
runs, tools, and handoffs.

## Starter shape

Create an `agent_tasks` dataset indexed by `task_id`.

| task_id | title | owner | status | priority | blocker | completion_evidence |
| --- | --- | --- | --- | --- | --- | --- |
| TASK-104 | Draft onboarding copy | Scribe | doing | P2 |  | PR link required |
| TASK-118 | Decide API-key copy | Rasul | blocked | P1 | Needs product decision | Slack thread |
| TASK-121 | Verify export flow | Forge | todo | P2 |  | Test output |

## Agent jobs

- Create tasks with clear ownership and status.
- Move work only when dataset instructions allow it.
- Surface blockers across long-running agent sessions.
- Keep completion evidence attached to each closed task.

## Workflow rules

Define the allowed statuses up front: `todo`, `doing`, `blocked`, `review`, and
`done` are usually enough. Add instructions for who may move a task, what counts
as evidence, and when an agent should ask before taking action.

## Connect it

Use [MCP access](/docs/connect-mcp) for agent updates and the
[Dataset API](/docs/dataset-api) for scripts. Use public previews only for
read-only status sharing.
