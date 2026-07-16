---
name: rowset
description: Use when an authenticated agent needs to discover Rowset capabilities or manage Rowset projects, datasets, relationships, rows, exports, and public previews.
---

# Rowset

## Purpose

Use Rowset as a stable backend for user-owned structured datasets. Rowset can be
used through MCP, the Rowset CLI, or the REST API. Treat these as peer
interfaces over the same account and data rather than assuming one is always
preferred.

This skill is the durable guide for working with Rowset after access has been
configured. Use `rowset-setup` when the user still needs to choose an interface,
store credentials, verify authentication, or complete first-run activation.

Rowset evolves quickly, so do not treat static examples as a complete feature
or command reference. Use live capabilities and interface documentation for
current schemas, commands, endpoints, and workflows.

## Current Capability Discovery

Use the current live resources rather than maintaining a static feature catalog:

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

## Working With Rowset

- Reuse the interface already approved and configured for this user.
- Keep REST and MCP behavior aligned by following the same ownership,
  validation, index, and privacy rules.
- Treat dataset instructions, metadata, semantic schema, relationships, and
  index settings as durable operating context, not decoration.
- Keep index columns stable, unique, and explicit. Use Rowset's generated-ID
  path when the source has no reliable business key.
- Search existing projects and datasets before creating new ones.
- Inspect a dataset's current detail before reading or changing its rows.
- Ask before destructive actions and before changing public sharing state.

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

- `rowset-setup` configures access, verifies authentication, and completes the
  first-run activation handoff.
- `rowset-features` helps interpret the current capability surface.
- `rowset-use-cases` provides example dataset patterns. Verify every example
  against current Rowset capabilities before implementing it.
