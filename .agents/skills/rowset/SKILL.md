---
name: rowset
description: Use when a user asks to connect an AI agent to Rowset, choose or configure Rowset MCP, CLI, or REST access, discover current Rowset capabilities, or manage Rowset datasets.
---

# Rowset

## Purpose

Use Rowset as a stable backend for user-owned structured datasets. Rowset can be
used through MCP, the Rowset CLI, or the REST API. Treat these as peer
interfaces over the same account and data rather than assuming one is always
preferred.

This skill is a durable setup and safety guide. Rowset evolves quickly, so do
not treat its static examples as a complete feature or command reference. Use
the live resources supplied in the setup prompt for current capabilities,
schemas, commands, endpoints, and workflows.

## Connection Inputs

The setup prompt should provide:

- Rowset MCP URL
- Rowset REST API base
- Rowset CLI guide
- Rowset API key
- Rowset skill URL or install command
- Rowset `llms.txt` documentation index
- Rowset docs and blog indexes
- Rowset generated REST API docs
- Rowset capabilities endpoint

If a needed value is missing, ask for it. Never ask the user to paste a key into
public chat or save it in a tracked file.

## Choose the Interface With the User

Before changing the user's environment or client configuration:

1. Inspect the current Rowset skill, `llms.txt`, capabilities response, and the
   documentation relevant to the available interfaces.
2. Evaluate MCP, CLI, and REST for the current runtime and likely workflow.
3. Give a short recommendation with the reason for it.
4. Ask the user which interface to configure. Do not silently install a CLI,
   edit an MCP configuration, create a secret, or wire up REST credentials.

Use practical criteria rather than agent-brand-specific instructions:

- MCP fits runtimes that support remote MCP and benefit from live tool/schema
  discovery.
- CLI fits terminal workflows that benefit from shell commands, scripts, and
  local file handling.
- REST fits applications or runtimes that already work naturally with HTTP and
  generated API schemas.

The recommendation is contextual, not a product preference. Follow the user's
choice.

## Configure the Approved Interface

1. Store the full API key in a private environment variable named
   `ROWSET_API_KEY` or an equivalent secret store. Do not print it in logs,
   screenshots, chats, generated files, or final responses. Do not commit it or
   save it in tracked configuration.
2. Follow the current documentation for the selected interface:
   - For MCP, configure the live server using its published connection details and send
     `Authorization: Bearer <key>` using the client's supported secret mechanism.
   - For CLI, use the current CLI guide and `rowset --help`; configure the API
     base when the instance is not the CLI default.
   - For REST, use the generated API docs and send
     `Authorization: Bearer <key>`.
3. Do not copy a setup command from memory when current client or Rowset docs
   are available.

## Complete Setup With Authentication

Make an authenticated user-info request the final setup step:

- MCP: call `get_user_info`.
- CLI: run `rowset user info`.
- REST: request `GET <Rowset REST API base>/user` with bearer authentication.

This final request verifies the connection, marks onboarding complete, and
starts the Rowset trial. If it fails, diagnose the selected interface using its
current docs and confirm the runtime holds the full key rather than only its
visible prefix.

After verification, report which interface is connected without exposing the
key. Ask what the user wants to do with Rowset next, and include one concise
recommendation when their context suggests a useful next action. Do not create
a first dataset or perform another Rowset task unless the user asks.

## Current Capability Discovery

After setup has been verified, use the setup prompt's live resources rather
than maintaining a static feature catalog here:

- MCP: inspect live tools and call `get_rowset_capabilities` when connected.
- CLI: use `rowset capabilities` and current `rowset --help` output.
- REST: read the capabilities endpoint and generated API docs.
- Any interface: use Rowset `llms.txt` to find current docs, guides, skills,
  use cases, and release-oriented resources.
- Use the Rowset docs and blog indexes for current product guidance, examples,
  decision guides, and evolving workflow recommendations.

Before working with an existing dataset, discover it and inspect its current
schema, instructions, metadata, relationships, and index semantics through the
selected interface. Search before creating duplicates. If no stable business
key exists for a new dataset, use Rowset's current generated-ID path documented
by the live capability guide.

## Safety Rules

- Keep authenticated datasets private by default.
- Access only the Rowset resources needed for the user's task.
- Ask before destructive actions such as deleting rows or datasets, archiving
  resources, clearing preview passwords, or replacing meaningful data.
- Ask before enabling or changing any public preview.
- Do not expose API keys, OAuth tokens, raw secrets, or private dataset contents.
- Public previews are read-only sharing surfaces, not authentication and not a
  replacement for private MCP, CLI, or REST access.
- Prefer programmatic Rowset interfaces over browser automation for agent work.
- Do not claim a capability exists unless a current Rowset resource exposes it.

## Companion Skills

- `rowset-features` helps interpret the current capability surface.
- `rowset-use-cases` provides example dataset patterns. Verify every example
  against current Rowset capabilities before implementing it.
