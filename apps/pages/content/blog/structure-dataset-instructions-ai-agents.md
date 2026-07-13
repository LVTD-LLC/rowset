---
title: How to structure dataset instructions for AI agents
description: Write dataset instructions that help AI agents inspect context, update rows safely, and avoid guessing workflow rules.
published_at: 2026-07-07
author: Rasul Kireev
keywords:
  - AI agent dataset instructions
  - dataset instructions
  - agent-managed datasets
  - Rowset metadata
topics:
  - datasets
  - agent workflows
  - instructions
canonical_url: https://rowset.lvtd.dev/blog/structure-dataset-instructions-ai-agents
image: /static/vendors/images/logo.png
image_alt: Rowset logo
robots: index, follow
---

Good dataset instructions tell an AI agent what the rows mean, which actions are
safe, which actions need review, and which fields should never be guessed. Put
durable workflow rules in `instructions`, machine-readable rules in `metadata`,
and ambiguous field meaning in column descriptions. Then tell the agent to call
`get_dataset` before row mutations.

That is the practical difference between a dataset that merely stores rows and a
dataset an agent can operate on across multiple sessions. Headers tell the agent
what columns exist. Instructions tell the agent how to behave when the user is
not restating every rule in the current chat.

## The short rule

Write dataset instructions as an operating contract, not as a second README.
The contract should answer five questions:

1. What job does this dataset support?
2. What row identity should the agent trust?
3. Which fields may the agent update directly?
4. Which state changes require evidence or review?
5. When should the agent stop and ask?

In Rowset, those instructions travel with the dataset and are visible through
[hosted MCP access](/docs/connect-mcp) and the [Dataset
API](/docs/dataset-api). That matters because MCP tools are designed to be
discoverable by models: the MCP tools specification says tools expose a name,
description, and input schema so a model can decide when to invoke them
([Model Context Protocol, 2025](https://modelcontextprotocol.io/specification/2025-03-26/server/tools)).
Dataset instructions add the missing local context for this specific table.

## What belongs in dataset instructions

Use plain text instructions for durable rules a human would normally explain
before delegating the work. Keep them short enough that an agent can read them
before each mutation.

Strong instructions usually include:

- the dataset's purpose
- the stable index column and what not to use as identity
- allowed status values and transition rules
- evidence required before closing or publishing something
- fields the agent may update without asking
- fields the agent must not invent, rewrite, or delete
- escalation rules for ambiguity, destructive actions, or missing evidence

Here is a compact task-board instruction block:

```text
This dataset tracks agent tasks. Use task_id as the stable row identity.
Allowed status values are todo, doing, blocked, review, and done.
Only move a task to done when completion_evidence contains a PR, URL, or
specific verification note. Keep blocker filled while status is blocked.
Do not delete rows or change task_id without asking the user.
Call get_dataset before updating rows, then update by task_id.
```

The best instructions are boring and concrete. "Keep this clean" is not useful.
"Only move a task to done when completion_evidence contains a PR, URL, or
specific verification note" is useful because it gives the agent a test.

## What belongs in metadata instead

Use JSON metadata when a rule should be parsed by software instead of only read
by the model. Metadata is better for values, thresholds, links, and workflow
configuration that another agent, script, or validation layer may inspect.

For the same task board, the metadata might be:

```json
{
  "workflow": {
    "status_values": ["todo", "doing", "blocked", "review", "done"],
    "default_status": "todo",
    "done_requires": ["completion_evidence"],
    "blocked_requires": ["blocker"]
  },
  "review": {
    "owner_field": "owner",
    "review_status": "review"
  }
}
```

This split mirrors the broader direction of structured AI interfaces. OpenAI's
Structured Outputs guide recommends clear key names and descriptions when a
model must produce schema-conforming JSON, and requires schemas to constrain
unexpected extra keys when strict outputs are enabled
([OpenAI, 2026](https://developers.openai.com/api/docs/guides/structured-outputs)).
Dataset metadata plays a similar role for the workflow: it gives machines a
stable shape instead of asking them to infer everything from prose.

Use both layers together. Put the operating rule in instructions so the agent
understands the why. Put the exact values or thresholds in metadata so future
automation can read them.

## Where column descriptions fit

Column descriptions are for field meaning. They are not the place for the whole
workflow.

A column named `owner` may mean assignee, account owner, vendor, product owner,
or person responsible for the next action. A column named `status` may mean lead
stage, task state, QA outcome, or editorial stage. Add descriptions wherever a
human would otherwise need to explain the column.

For example:

```json
{
  "column_types": {
    "status": {
      "type": "choice",
      "description": "Current workflow state for the task",
      "choices": ["todo", "doing", "blocked", "review", "done"]
    },
    "completion_evidence": {
      "type": "text",
      "description": "URL, PR link, test output, or note proving the task is done"
    }
  }
}
```

Use the [schema design guide](/docs/design-schema) when you need semantic column
types, choice values, references, or descriptions. Use the [index-column
guide](/blog/choose-index-column-agent-rows) when you are deciding how the agent
should find the same row again later.

## A reusable instruction template

Start with this template when creating a Rowset dataset for agent work:

```text
Purpose:
This dataset tracks [job/workflow] for [team/project].

Identity:
Use [index_column] as the stable row identity. Do not identify rows by
[unsafe_columns] because those values can change or collide.

Safe updates:
The agent may update [fields] when the user request is explicit and the target
row is found by [index_column].

State rules:
[status_field] may only use [allowed_values]. Move a row to [terminal_state]
only when [evidence_field] contains [required_evidence].

Review rules:
Ask before [destructive_actions], [ambiguous_actions], or [high-risk_actions].

Startup:
Call get_dataset before row operations. Confirm headers, instructions,
metadata, column schema, relationships, and index_column before writing.
```

The `Startup` section is important. Anthropic's prompt engineering guidance
emphasizes clear, explicit instructions and enough context for the model to know
the user's norms and workflow
([Anthropic, 2026](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)).
For datasets, the reliable way to provide that context is to make the agent
inspect the dataset before acting.

## Example: content pipeline

For a content pipeline, create a `content_queue` dataset indexed by `slug`.
The instructions can stay tight:

```text
This dataset tracks editorial work from idea to published page.
Use slug as the stable row identity. Do not identify rows by title because
titles change during editing.

Allowed stage values are idea, brief, draft, review, scheduled, and published.
Only move a row to published when canonical_url is non-empty and publish_date is
set. Only move a row to scheduled when owner is assigned.

The agent may update stage, owner, notes, target_keyword, canonical_url, and
publish_date when the user request is explicit. Ask before deleting rows,
changing slug, or replacing canonical_url on a published row.

Call get_dataset before updates and patch rows by slug.
```

Useful metadata:

```json
{
  "workflow": {
    "stage_values": ["idea", "brief", "draft", "review", "scheduled", "published"],
    "terminal_stage": "published",
    "published_requires": ["canonical_url", "publish_date"]
  },
  "handoff": {
    "source_repo": "https://github.com/example/site",
    "review_channel": "#content"
  }
}
```

This maps cleanly to Rowset's [content pipeline use
case](/use-cases/content-pipeline). The instructions tell the agent how to
move editorial work. The metadata gives future automation a parseable status
model.

## Example: feedback triage

For feedback triage, create a `feedback_items` dataset indexed by
`feedback_id` or the source ticket id.

```text
This dataset tracks product feedback that needs triage.
Use feedback_id as the stable row identity. Do not identify rows by message
text because messages can be summarized or merged.

Allowed status values are new, triaged, planned, shipped, and closed.
Only move feedback to shipped when release_note_url or pr_url is present.
Never rewrite original_message; add interpretation in summary or theme instead.

The agent may update theme, summary, status, priority, owner, duplicate_of,
release_note_url, and pr_url. Ask before closing feedback without a linked
resolution, deleting rows, or merging two items.

Call get_dataset before updates and patch rows by feedback_id.
```

Useful metadata:

```json
{
  "workflow": {
    "status_values": ["new", "triaged", "planned", "shipped", "closed"],
    "immutable_fields": ["feedback_id", "original_message", "source_url"],
    "shipped_requires_any": ["release_note_url", "pr_url"]
  }
}
```

This pairs naturally with the [feedback triage use
case](/use-cases/feedback-triage). The important rule is that agents may
interpret feedback, but they should not rewrite the original evidence.

## Example: product inventory

For a product catalog, create a `products` dataset indexed by `sku` or the
upstream product id.

```text
This dataset tracks products the agent may enrich and maintain.
Use sku as the stable row identity. Do not identify products by name because
names can change and variants can share similar names.

The agent may update description, price, status, supplier_url, and notes when
the source is explicit. Ask before changing sku, deleting a product, changing
currency assumptions, or marking a product retired without source evidence.

Treat price as USD unless currency is set. If price is inferred from a source,
store the source URL in source_url.

Call get_dataset before updates and patch rows by sku.
```

Useful metadata:

```json
{
  "workflow": {
    "default_currency": "USD",
    "retired_requires": ["source_url"],
    "protected_fields": ["sku"]
  }
}
```

This follows the same pattern as the [product or inventory catalog use
case](/use-cases/product-inventory-catalog): stable identity first, source
evidence second, safe updates third.

## Common mistakes

The most common mistake is writing instructions that sound helpful but do not
change agent behavior. "Be careful with updates" does not tell the agent what to
check. Replace it with "Ask before changing `slug` or deleting rows."

Other mistakes:

- putting all workflow rules in the user's chat instead of the dataset
- using metadata for long human-readable paragraphs
- using instructions for values that should be structured as JSON
- forgetting to name the index column
- allowing terminal states without evidence requirements
- saying "use the obvious row" instead of requiring by-index lookup
- omitting immutable source fields such as `original_message` or `source_url`
- treating public previews as the agent's write path

Public previews are for human review. The agent should use private MCP or REST
access for reads and writes, with the right API-key permission level. If the
connection path is still unclear, read [MCP vs REST for AI
agents](/blog/mcp-vs-rest-ai-agents).

## A quick QA checklist

Before giving an agent write access, read the instructions and check:

1. The dataset purpose is obvious.
2. The index column is named.
3. Unsafe identity columns are named.
4. The agent knows which fields it may update.
5. Status or stage values are explicit.
6. Done, shipped, closed, or published states require evidence.
7. Destructive actions require confirmation.
8. Immutable source fields are protected.
9. Metadata holds parseable rules.
10. Column descriptions explain ambiguous fields.

If the instructions pass that checklist, the agent has a much better chance of
acting consistently across runs.

## FAQ

### Are dataset instructions the same as a system prompt?

No. A system prompt controls the agent session or client. Dataset instructions
belong to one dataset and should describe how that dataset should be read and
updated. The agent still needs its normal operating rules, but dataset-specific
rules should live with the data.

### Should every Rowset dataset have instructions?

Every agent-operated dataset should have at least a short instruction block.
Human-only review datasets can be lighter, but any dataset an agent may mutate
should explain row identity, safe fields, evidence rules, and stop conditions.

### Should rules go in instructions or metadata?

Use instructions for prose the model should follow. Use metadata for values and
rules software may parse, such as allowed states, required evidence fields,
owner fields, repository URLs, or review-channel names. Use both when the rule
needs human meaning and machine-readable structure.

### How long should dataset instructions be?

Short enough for the agent to read before every write. For most datasets, 150 to
300 words is enough. If the rules are longer, split stable values into metadata
and clarify the columns with descriptions.
