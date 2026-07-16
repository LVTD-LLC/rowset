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

1. Read the setup skill, `llms.txt`, and current capability resources.
2. Compare MCP, CLI, and REST, recommend one, and ask the user which to configure.
3. Load the public `/api/capabilities` response and current interface docs.
4. Configure only the approved interface and keep the API key in a secret store.
5. Make authenticated user-info the first authenticated action and final setup step so the connection is
   verified, onboarding completes, and the trial starts.
6. Use existing user context and read-only Rowset discovery to suggest two to four
   useful project, section, and dataset structures, then ask which one to create.
7. If the agent runtime supports scheduled tasks, separately offer an opt-in
   daily automation for Rowset tips grounded in current Rowset resources.

## Capability guide

The same concise, structured capability guide is available through
`get_rowset_capabilities`, `rowset capabilities`, and `/api/capabilities`. It
groups Rowset features by workflow:

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

The repo skill package includes three skills:

- `rowset` for setup, MCP authentication, and safe default workflows
- `rowset-features` for explaining supported capabilities
- `rowset-use-cases` for choosing dataset shapes for common workflows

Install them with:

```bash
{{ skill_install_command }}
```

The app serves the skill markdown at:

```text
{{ site_url }}/SKILL.md
{{ features_skill_url }}
{{ use_cases_skill_url }}
```

## What agents should treat as current

- The live capability guide is the current workflow and feature reference.
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
