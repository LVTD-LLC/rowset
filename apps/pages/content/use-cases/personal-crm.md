---
title: Agent-managed personal CRM
description: Use Rowset as an agent-managed personal CRM for people, companies, conversations, follow-ups, and relationship context.
keywords: agent CRM, personal CRM, Rowset use case
---

# Agent-managed personal CRM

Use Rowset when you want a trusted agent to maintain relationship context without
turning every follow-up into a manual spreadsheet chore.

Keep recalled preferences in agent memory and current contact fields in the CRM
dataset. The guide to [AI agent memory vs structured
state](/blog/ai-agent-memory-vs-state) shows how to choose the authoritative
home for each fact.

## Starter shape

Create a `people` dataset. Use `email` as the index when contacts have reliable
email addresses, or `person_id` when one person can have several addresses.

People dataset indexed by email or person_id.

| email | name | company | relationship_stage | last_interaction | next_action | notes |
| --- | --- | --- | --- | --- | --- | --- |
| alex@example.com | Alex Morgan | Northstar Labs | follow up | 2026-07-01 | Send pricing notes | Asked for implementation examples |
| sam@studio.dev | Sam Lee | Studio Dev | warm | 2026-06-24 | Share demo recap | Intro from May conference |
| nora@acme.com | Nora Patel | Acme | waiting | 2026-06-28 | Check in after demo | Wants security details |

## Agent jobs

- Add people and companies from meeting notes, emails, or chat summaries.
- Update relationship stage after each conversation.
- Find stale promises before they become dropped balls.
- Export a CSV or JSONL snapshot when you want a backup or handoff.

## Dataset context and semantic schema

Add instructions that define stage meanings, follow-up rules, and what counts as
private notes. Mark `email` as an email column, `last_interaction` as a date,
and `next_action` as free text. Keep the agent honest: it should update rows
only from trusted notes or direct user instruction.

## Connect it

Use [MCP access](/docs/connect-mcp) first. If MCP is unavailable, use the
[Dataset API](/docs/dataset-api) with a bearer API key. Public previews should
stay off unless you deliberately want a read-only relationship board.
