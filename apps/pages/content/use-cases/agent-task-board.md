---
title: Agent task board
description: Use Rowset as an agent task board with durable status, owner, priority, blocked-state, and handoff rows.
keywords: agent task board, AI task tracker, Rowset use case
date_modified: 2026-10-08
---

# Agent task board

Use Rowset as a small task ledger when agent work needs durable state across
runs, tools, and handoffs. Your agent maintains the rows; Rowset stores the
board. It does not run the agent or schedule the work for you.

Task status is structured operational state, not a memory the agent may or may
not retrieve. See [AI agent memory vs structured
state](/blog/ai-agent-memory-vs-state) for the architecture boundary.
For the full schema, transition rules, retry behavior, and review contract, read
[how to build a durable AI agent task board](/blog/ai-agent-task-management).

## Starter shape

Create an `agent_tasks` dataset indexed by `task_id`. The rows below illustrate
the shape; do not copy them into your real board as assigned work.

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

Because task agents often retry after tool or network failures, pair the board
with the [idempotent AI-agent update pattern](/blog/idempotent-ai-agent-updates).
Use `task_id` as the stable identity, write absolute status values, and verify
the row before replaying an uncertain update.

## Create your private task board

First [connect your agent to Rowset](/docs/quickstart) and verify authenticated
access. Then send the following prompt to that connected agent. It authorizes
one empty task dataset, not execution of the tasks it will eventually contain.
Replace the bracketed project name before sending it.

```text
Create a private agent task board in my Rowset project [project name].

Search for that project with a limit of 3 and inspect the matching project.
If there is no exact match, ask me which project to use; do not create one.
Within that project, search for agent_tasks with a limit of 3. Inspect any
matching dataset before creating anything. Reuse an exact compatible board.
If its purpose, schema, index, instructions, or privacy settings conflict
with this request, stop and report the conflict instead of overwriting it.

If no matching board exists, create one empty dataset named agent_tasks.
Use text columns: task_id, title, owner, status, priority, blocker,
completion_evidence. Use task_id as the stable index and keep previews off.
Use the current interface schema and its duplicate-name prevention option.
Do not invent tasks or import the example rows from the use-case page.

Store these workflow instructions on a new board:
- Allowed statuses: todo, doing, blocked, review, done.
- Read the dataset instructions and the task by task_id before an update.
- Only act on tasks I explicitly assign and authorize you to perform.
- Record a blocker when work cannot continue; do not mark it done.
- Attach real completion evidence before moving work to review.
- Mark done only after the required reviewer accepts that evidence.
- Ask before deleting records or enabling a public preview.

Read the dataset back. Confirm its project, columns, task_id index,
instructions, and private status. Return its key and whether you created
or reused it. Stop without starting any tasks.
```

This prompt follows the current [first-dataset workflow](/docs/quickstart) and
[dataset concepts](/docs/core-concepts), checked October 8, 2026. The statuses
and review rules are instructions for your agent, not server-enforced task
transitions or a scheduling feature.

## Verify one real task before handing off

Supply a real task ID, title, owner, priority, and definition of done. Ask the
agent to inspect the board, check that ID before creating a row, and read it
back afterward. Keep the board empty until you have a real task; an empty
verified schema is a useful starting point.

In a later agent session, provide the saved dataset key and task ID. Ask it to
read the current row and board instructions, summarize the next authorized
action, and wait before making changes. This checks that the handoff recovers
stored state rather than guessing from an earlier chat.

If a write times out, fetch the same task ID before retrying. A status field is
not a lock: do not let two agents independently claim the same task and assume
that one must lose. Use a single writer or coordinate assignment outside the
board. The [full task-management guide](/blog/ai-agent-task-management) covers
transition and retry rules in more detail.

## Connect it

Use [MCP access](/docs/connect-mcp) for agent updates and the
[Dataset API](/docs/dataset-api) for scripts. Use public previews only for
read-only status sharing.
