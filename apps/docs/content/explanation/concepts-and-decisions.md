---
title: Concepts and decisions
description: Understand how Rowset fits agent workflows, when to use MCP or REST, and how to choose dataset shapes.
keywords: Rowset concepts, agent-managed dataset, MCP vs REST, Rowset playbooks
---

# Concepts and decisions

Use this section when you are deciding what to build, not looking up an endpoint
or following setup steps.

Rowset works best when a trusted AI agent needs a private, structured place to
create, inspect, update, export, and share rows. The docs teach the mechanics;
these pages explain the product choices behind those mechanics.

## Core concepts

- [What is an agent-managed dataset?](/blog/agent-managed-datasets) explains why
  stable row identity, schema context, dataset instructions, and private
  programmatic access matter for delegated agent work.
- [How to choose an index column for agent-managed rows](/blog/choose-index-column-agent-rows)
  explains when to use a business key such as `sku`, `email`, `slug`, or
  `task_id`, and when to let Rowset generate `rowset_id`.
- [When should an AI agent use MCP instead of REST?](/blog/mcp-vs-rest-ai-agents)
  explains the protocol decision for interactive agents, scripts, backend jobs,
  and constrained runtimes.

## Product decisions

- [Database MCP server: when to use Rowset instead](/playbooks/database-mcp-server)
  compares direct database MCP access with Rowset's narrower hosted dataset
  backend.
- [Use cases](/use-cases/) show practical starter shapes for personal CRMs,
  agent task boards, feedback triage, content pipelines, product catalogs, and
  bug or QA trackers.

## Apply the concepts

1. Choose a real workflow from the use-case library.
2. Pick the stable index value the agent and source system will both recognize.
3. Store workflow rules in dataset `instructions` or `metadata`.
4. Connect a trusted agent through hosted MCP when the runtime supports it.
5. Use REST when the caller is a script, backend service, or deterministic job.

For setup steps, start with [Get started](/docs/tutorials/get-started/) or
[Connect MCP](/docs/how-to-guides/connect-mcp/).
