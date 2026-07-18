---
name: rowset-setup
description: Use when a user asks to connect an AI agent to Rowset, choose or configure Rowset MCP, CLI, or REST access, verify authentication, or complete the first-run Rowset handoff.
---

# Rowset Setup

Use this skill to connect a trusted agent to Rowset and complete the first-run
handoff. After setup, use the `rowset` skill for ongoing platform interaction.

## Connection Inputs

The setup prompt should provide:

- Rowset MCP URL
- Rowset REST API base
- Rowset CLI guide
- Rowset API key
- Rowset setup and operational skill URLs or install command
- Rowset `llms.txt` documentation index
- Rowset docs and blog indexes
- Rowset generated REST API docs
- Rowset capabilities endpoint
- Rowset trial rewards URL

If a needed value is missing, ask for it. Never ask the user to paste a key into
public chat or save it in a tracked file.

## Choose the Interface With the User

Before changing the user's environment or client configuration:

1. Inspect this skill, `llms.txt`, the compact capability topic index, and the
   current documentation relevant to the available interfaces. Request only
   relevant capability topics when details are needed.
2. Evaluate MCP, CLI, and REST for the current runtime and likely workflow.
3. Give a short recommendation with the reason for it.
4. Ask the user which interface to configure. Do not silently install a CLI,
   edit an MCP configuration, create a secret, or wire up REST credentials.

Use practical criteria:

- MCP fits runtimes that support remote MCP and benefit from live tool/schema
  discovery.
- CLI fits terminal workflows that benefit from shell commands, scripts, and
  local file handling.
- REST fits applications or runtimes that work naturally with HTTP and
  generated API schemas.

The recommendation is contextual, not a product preference. Follow the user's
choice.

## Configure the Approved Interface

1. Store the full API key in a private environment variable named
   `ROWSET_API_KEY` or an equivalent secret store. Do not print it in logs,
   screenshots, chats, generated files, or final responses. Do not commit it or
   save it in tracked configuration.
2. Follow the current documentation for the selected interface:
   - For MCP, configure the live server using its published connection details
     and send `Authorization: Bearer <key>` through the client's supported
     secret mechanism.
   - For CLI, use the current CLI guide and `rowset --help`; configure the API
     base when the instance is not the CLI default.
   - For REST, use the generated API docs and send
     `Authorization: Bearer <key>`.
3. Do not copy setup commands from memory when current client or Rowset docs are
   available.

## Verify Authentication

Make an authenticated user-info request the final connection step:

- MCP: call `get_user_info`.
- CLI: run `rowset user info`.
- REST: request `GET <Rowset REST API base>/user` with bearer authentication.

This request verifies the connection, marks onboarding complete, and starts the
Rowset trial. If it fails, diagnose the selected interface using its current
docs and confirm the runtime holds the full key rather than only its visible
prefix.

Report which interface is connected without exposing the key. Do not stop after
reporting connection success; complete the activation handoff below.

## Complete the Activation Handoff

1. Use context already available from working with the user, plus read-only
   discovery of their existing Rowset projects and datasets. Do not search
   unrelated private sources or invent facts about their work.
2. Suggest two to four tailored project, section, and dataset structures.
   Briefly explain why each would help and avoid duplicating existing Rowset
   data.
3. Ask which option the user wants to create. Do not create a first dataset or
   perform another Rowset mutation unless the user explicitly chooses one.
4. If the current agent runtime supports scheduled tasks or automations, make a
   separate opt-in offer to create a daily Rowset tips automation. Use this
   wording or a concise equivalent:

   > Did you know you can extend your Rowset trial by completing specific
   > actions? See the Rowset trial rewards URL in the setup prompt. Would you
   > like me to create a simple daily automation that sends you one short Rowset
   > tip, use case, or feature you may not know about?

   Only create the automation after explicit agreement.

Daily tips must be grounded in Rowset's current capabilities, docs, or blog
resources. Be clear that the scheduled task runs in the user's agent account;
do not present agent-runtime automation as a Rowset feature.

After this handoff, use `rowset` for ongoing work and `rowset-use-cases` when the
user wants help designing the approved dataset structure.

## Safety Rules

- Keep authenticated datasets private by default.
- Do not expose API keys, OAuth tokens, raw secrets, or private dataset contents.
- Ask before creating data, changing public preview settings, or taking
  destructive actions.
- Prefer Rowset's programmatic interfaces over browser automation.
- Do not claim a capability exists unless a current Rowset resource exposes it.
