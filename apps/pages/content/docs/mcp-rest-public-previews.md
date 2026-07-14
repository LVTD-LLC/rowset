---
title: MCP, REST, and public previews
description: Understand when agents should use Rowset MCP, when systems should use REST, and where public previews fit.
keywords: Rowset MCP, Rowset REST API, public previews, agent authentication
---

# MCP, REST, and public previews

Rowset has three surfaces that look similar from a distance but solve different
jobs:

- **MCP** is the preferred path for trusted AI agents that can discover tools.
- **REST** is the portable HTTP path for scripts, services, and agent runtimes
  without MCP support.
- **Public previews** are read-only browser pages for human review.

The important boundary is authentication. MCP and REST are private,
programmatic paths backed by API keys. Public previews are sharing paths, not
agent authentication.

## Use MCP for agent work

Use MCP when the agent runtime can connect to Rowset's hosted MCP endpoint and
send a bearer token. The agent can discover tools, inspect schemas, verify the
connected account, load Rowset capabilities, and operate on datasets without
scraping the browser.

This is the best fit for workflows like personal CRMs, task boards, feedback
triage, content queues, catalogs, and QA trackers.

## Use REST for portable integrations

Use REST when the caller is a backend service, script, scheduled job, or agent
runtime that cannot use MCP. REST is also useful when you need explicit HTTP
requests, generated API docs, or conventional client code.

The REST API uses the same ownership boundary: send
`Authorization: Bearer <key>`, then operate only inside the authenticated
Rowset account.

## Use public previews for humans

Use a public preview when a teammate, client, or reviewer needs to inspect a
dataset in a browser without an API client. Previews are read-only. Add a
password when the link should not be casually forwarded, and disable the preview
when the sharing window is over.

Do not use public previews as the path for agents to read or update data. Use
MCP or REST for that.

## Common route

1. Connect a trusted agent with MCP.
2. Let the agent create or update a private dataset.
3. Use REST only when a script or service needs the same data.
4. Enable a public preview only when a human needs a read-only view.
5. Export a snapshot when another tool expects a file.

## Related docs

- [Connect over MCP](/docs/connect-mcp)
- [Dataset API](/docs/dataset-api)
- [Share a public preview](/docs/share-public-previews)
- [MCP tool reference](/docs/mcp-tools)
- [When should an AI agent use MCP instead of REST?](/blog/mcp-vs-rest-ai-agents)
