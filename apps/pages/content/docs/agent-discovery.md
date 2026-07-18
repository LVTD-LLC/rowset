---
title: Help agents discover Rowset
description: Help AI agents discover Rowset features, tool schemas, skills, and workflow guides.
keywords: Rowset agents, llms.txt, MCP discovery, Rowset skills
---

# Help agents discover Rowset

Rowset is designed so agents do not have to rely on stale prompt text. A trusted
agent should use live capabilities and current interface documentation before
creating or changing data. MCP, CLI, and REST are peer access methods; the agent
should recommend one for its runtime and the user's workflow, then ask which
interface to configure.

## Recommended startup order

1. Read `rowset-setup` and the connection documentation needed for the current
   runtime.
2. Compare MCP, CLI, and REST, recommend one, and ask the user which to configure.
3. Configure only the approved interface and keep the API key in a secret store.
4. For a new or failing connection, make authenticated user-info the final setup
   action so the connection is verified, onboarding completes, and the trial starts.
5. Start the user's task. Use exact tool, command, or endpoint schemas for the
   operation at hand. Load capability topics only for unfamiliar features or
   troubleshooting.
6. When the relevant dataset is unknown, search with an explicit limit of 3, select one,
   and load that dataset's full context. Skip discovery when the user supplied a
   dataset key or URL.
7. If the agent runtime supports scheduled tasks, separately offer an opt-in
   daily automation for Rowset tips grounded in current Rowset resources.

Do not load capabilities or list datasets merely because a session started.
Do not enumerate unrelated projects or datasets during discovery.

## Capability guide

The same progressive capability guide is available through
`get_rowset_capabilities`, `rowset capabilities`, and `/api/capabilities`. A
bare call, command, or request returns a compact `available_topics` index. Use
one or more topic IDs to retrieve the detailed feature groups needed for the
task. Use cases are opt-in, while full mode retrieves the complete guide.

Examples:

```text
MCP:  get_rowset_capabilities {"topics":["rows","schema"]}
CLI:  rowset capabilities --topic rows --topic schema
REST: GET /api/capabilities?topics=rows,schema
```

Add `include_use_cases=true`, `--include-use-cases`, or
`"include_use_cases": true` only when examples help. For the complete guide,
use `full=true`, `--full`, or `{"full": true}` without topics.

Available topics group Rowset features by workflow:

- account and MCP setup
- datasets
- dataset context and semantic schema
- schema mutations
- dataset relationships
- projects
- rows
- image and audio assets
- public previews
- archive, restore, and exports

Use the guide for workflow semantics. Use MCP tool discovery, CLI help, or
generated REST API docs for exact current operations and inputs.

## llms.txt

Rowset also publishes a generated text page for agents and search tools:

```text
{{ llms_txt_url }}
```

The page includes the MCP endpoint, REST API base, generated API docs link,
skill URLs, capability groups, use-case guides, and privacy guardrails. It does
not include user API keys or private dataset contents. Its content index lists
documentation only; blog posts, comparison pages, and use-case marketing pages
are intentionally omitted.

## Installable skills

The repo skill package includes four skills:

- `rowset-setup` for interface choice, authentication, and first-run activation
- `rowset` for ongoing platform interaction and safety rules
- `rowset-features` for explaining supported capabilities
- `rowset-use-cases` for choosing dataset shapes for common workflows

Install them with:

```bash
{{ skill_install_command }}
```

The app serves the skill markdown at:

```text
{{ site_url }}/SKILL.md
{{ setup_skill_url }}
{{ features_skill_url }}
{{ use_cases_skill_url }}
```

## What agents should treat as current

- The live capability topic index and selected details are the current workflow
  and feature reference.
- MCP `tools/list`, CLI help, and generated REST docs are the exact sources for
  their respective interface operations and schemas.
- `get_dataset` is the current per-dataset context source before row work.
- Generated API docs are the exact REST schema source.
- Public docs and skills explain stable workflows and guardrails.

## Privacy guardrails

Agents should keep private authenticated access as the default, store keys only
in private environment variables or secret stores, and ask before destructive
actions such as deleting rows, archiving datasets, or clearing preview
passwords.

Public previews are read-only browser sharing. They are not authentication and
do not replace MCP or REST access.

## Related docs

- [Connect over MCP](/docs/connect-mcp)
- [Configure agent access](/docs/configure-agent-access)
- [MCP tool reference](/docs/mcp-tools)
