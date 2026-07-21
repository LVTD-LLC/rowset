---
title: How to share AI-agent data safely
description: Choose private agent access, exports, or read-only previews by audience, allowed actions, and sharing lifetime.
published_at: 2026-07-16
author: Rasul Kireev
keywords:
  - share AI agent data
  - share agent-managed datasets safely
  - AI agent data access
  - secure dataset sharing
topics:
  - data sharing
  - agent security
  - dataset access
canonical_url: https://rowset.lvtd.dev/blog/share-ai-agent-data-safely
image: /static/vendors/images/logo.png
image_alt: Rowset logo
robots: index, follow
---

Share AI-agent data through the narrowest surface that fits the recipient's job. Give a trusted agent private MCP or REST access when it must work on live rows. Send an authenticated export when someone needs a point-in-time file. Enable a read-only public preview only for data you intend to expose to anyone who receives the link and, when configured, its password.

The decision comes down to three questions:

1. **Audience:** who needs the data?
2. **Action:** do they need to inspect, download, or change it?
3. **Lifetime:** should access stay live, expire after a handoff, or end after one review?

That **audience -> action -> lifetime** contract is more useful than labeling a dataset "private" or "public." It produces a concrete access path and a clear cleanup step.

## Choose the sharing path first

| Recipient's job | Rowset path | Access | Best cleanup step |
|---|---|---|---|
| A trusted agent needs live rows and tool discovery | MCP with a scoped API key | Private, authenticated, read or write by key permission | Revoke or rotate the key when the job ends |
| A script or service needs live rows | Dataset API with a scoped API key | Private, authenticated, read or write by key permission | Revoke or rotate the key when the integration ends |
| A person or another system needs a snapshot | Authenticated export | Point-in-time file outside Rowset after download | Delete or control the copied file in its destination |
| A reviewer needs a browser table or public JSON feed | Public preview, optionally password-protected | Read-only for anyone with the required sharing material | Disable the preview after the review window |

Start with private access. Move to an export or preview only when the recipient cannot use the authenticated path or when a file or browser view is the actual deliverable.

## Why the recipient's action matters more than the format

A CSV file and a browser table can display the same rows, but they create different security boundaries. A downloaded file becomes a separate copy. A public preview remains a live view controlled by the dataset's sharing setting. An MCP or REST client receives live private access and may be able to mutate rows if its key permits writes.

This is why "share the dataset" is incomplete. A safe request sounds more like this:

> Let the client review the current backlog in a browser until Friday. They must not edit rows. Use a password and disable the preview after review.

The request names the audience, allowed action, and lifetime. An agent can map it to the correct Rowset operation without guessing whether "share" means a key, file, or link.

## Use private MCP or REST for working agents

Use [hosted MCP](/docs/connect-mcp) when a trusted agent needs to discover Rowset tools and work with live datasets. Use the [Dataset API](/docs/dataset-api) for scripts, services, scheduled jobs, or runtimes that need explicit HTTP calls. Both are authenticated programmatic paths.

Create the smallest useful agent key:

- **Read** for inspection, reporting, and exports.
- **Read + write** for agents that create or update datasets, rows, relationships, or preview settings.
- **Admin** only for trusted automation that must create other agent keys.

The current Model Context Protocol authorization guidance recommends authorization for servers that access user-specific data. It also recommends short-lived tokens, token validation, HTTPS, narrow scopes, secure token storage, and keeping credentials out of logs ([MCP authorization guidance, checked July 2026](https://modelcontextprotocol.io/docs/tutorials/security/authorization)). Rowset uses bearer API keys rather than claiming the full OAuth flow described in that guide, but the operational lesson still applies: possession of the credential grants its configured access.

Store the key in the agent runtime's secret environment, such as `ROWSET_API_KEY`. Do not paste it into a public issue, shared screenshot, repository file, or exported dataset. The [agent access guide](/docs/configure-agent-access) shows the current bearer-token setup and permission levels.

Private authentication is not enough on its own. Authorization must also be enforced for the requested dataset. OWASP's 2023 API Security guidance says every endpoint that accepts an object identifier should check whether the authenticated user may perform the requested action on that object ([OWASP API1:2023](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/)). That is the boundary you want from a structured data backend: a valid token should not become access to another account's rows merely because the caller knows an identifier.

## Use an export for a point-in-time handoff

Use an export when the recipient needs a file rather than continued access. Rowset currently supports authenticated dataset exports in CSV, JSONL, XLSX, and SQLite formats. The [export and troubleshooting guide](/docs/archive-export-troubleshoot) lists the current endpoints.

An export freezes the data at download time. That is useful for an audit packet, offline analysis, import into another tool, or a handoff to someone who should not receive a live credential.

The tradeoff is control. Once downloaded, the file is a separate copy. Disabling a Rowset preview or revoking an API key does not erase a CSV from someone else's drive or inbox. Before exporting:

1. Remove columns the recipient does not need.
2. Check whether row values contain secrets, personal data, internal notes, or source URLs with embedded credentials.
3. Name the intended recipient and destination.
4. Record the snapshot date so nobody mistakes it for current state.
5. Decide who is responsible for deleting or retaining the copy.

Use a read-only key for export-only automation. A process that only downloads snapshots does not need permission to change the source dataset.

## Use a public preview for deliberate read-only sharing

A Rowset public preview is a browser-friendly, read-only view with a corresponding public JSON API. It is disabled by default for a private dataset. When enabled, it can be open to anyone with the link or protected by a password.

Use a preview for a client review, stakeholder board, public catalog, or another case where a live read-only view is the product of the sharing decision. Follow the [public preview setup](/docs/share-public-previews) to enable it, set the page size, and add a password when appropriate.

Password protection reduces casual access, but it does not turn a preview into private MCP or REST authentication. Anyone with the link and password can use the preview or public read API. Do not put sensitive rows behind a shared password and describe them as private.

Treat the preview as a publication surface:

- Review every visible column and row before enabling it.
- Remove internal instructions, notes, identifiers, and metadata that the audience does not need.
- Send the link and password through separate channels when the risk warrants it.
- Do not place the password in the URL; protected public API requests use the `X-Rowset-Public-Password` header.
- Disable the preview when the sharing window ends.

Archiving a Rowset dataset disables its public preview. That is a recovery mechanism for inactive datasets, not a substitute for a planned end date.

## Build a share-safe view instead of exposing the working dataset

The safest shared dataset often is not the agent's working dataset. Working rows may contain operational notes, source identifiers, internal statuses, or instructions that are useful to the agent but wrong for a client or public audience.

Create a separate review dataset when the audiences need different schemas. For a feedback workflow, the private dataset might contain customer names, source messages, severity reasoning, owner notes, and internal next actions. A client-facing review dataset might contain only a public reference, theme, status, and published response.

This separation has three advantages:

1. The shared schema is an explicit allowlist instead of a growing denylist.
2. Future private columns do not appear automatically in the public surface.
3. The agent gets a clear publication step that can be reviewed and repeated.

Use stable references between the two datasets if the workflow needs traceability. The guide to [modeling relationships between agent-managed datasets](/blog/relationship-modeling-agent-datasets) explains when a Rowset reference, external identifier, or source URL is appropriate.

## Put the sharing contract in dataset instructions

Persistent instructions help a future agent repeat the same boundary. Keep them concrete:

```text
This is the private working feedback dataset.
Never enable its public preview.
For client review, copy only feedback_ref, theme, status, and public_response
into the client_feedback_review dataset.
Ask before exporting either dataset.
If a review preview is enabled, require a password and disable it after the
date in review_expires_at.
Never place API keys, access tokens, or passwords in row values.
```

The instructions do not enforce access control by themselves. They tell the agent how to use the controls correctly. API-key permissions, account ownership checks, and public preview settings remain the actual enforcement points.

For a fuller instruction pattern, see [how to structure dataset instructions for AI agents](/blog/structure-dataset-instructions-ai-agents).

## A pre-share checklist for agents and humans

Before sharing agent-managed data, confirm each line:

- **Audience:** I can name the people, agent, script, or public audience receiving access.
- **Action:** The recipient gets only the ability to inspect, export, or edit that the job requires.
- **Lifetime:** The access has an end condition, review date, or continuing owner.
- **Data minimization:** The surface excludes columns and rows the recipient does not need.
- **Credential handling:** No raw API key, token, or password appears in prompts, logs, screenshots, source control, or dataset rows.
- **Ownership:** Private MCP and REST calls remain inside the authenticated Rowset account.
- **Public boundary:** A preview contains only data suitable for anyone who obtains the link and required password.
- **Copies:** Export recipients understand that the snapshot is a separate copy and know its date.
- **Cleanup:** Someone is responsible for revoking the key, disabling the preview, or deleting the copied file.

If any answer is unclear, keep the dataset private and resolve the ambiguity first.

## Common data-sharing mistakes

### Sending a write key to a read-only consumer

Use a read key for inspection and exports. Extra permission creates risk without helping the recipient finish the job.

### Treating a public link as private authentication

A password-protected preview is still a shared read-only surface. Use MCP or REST when access must remain inside an authenticated agent workflow.

### Exporting the whole working schema

An export copies every included field beyond Rowset's live access controls. Build a reduced dataset or remove unnecessary columns before download.

### Sharing forever because the link still works

Every temporary preview and integration key needs an owner and end condition. Disable or revoke it when the work ends.

### Relying on instructions as the security boundary

Instructions guide agent behavior. They do not replace permissions, ownership checks, secret storage, or deliberate public settings.

## FAQ

### What is the safest way to share data with an AI agent?

Give a trusted agent a scoped private credential through its secret environment, then use MCP or REST. Start with read permission and add write access only when the job requires mutation. Keep credentials out of prompts, logs, screenshots, repositories, and dataset rows.

### Is a password-protected Rowset preview private?

It is protected read-only sharing, not private agent authentication. Anyone with the link and password can view the dataset or call its public read API. Use private MCP or REST access for sensitive data and authenticated agent work.

### Should I share a live dataset or export a file?

Share a live surface when the recipient needs current data. Export a file when the recipient needs a point-in-time snapshot or cannot use authenticated access. Remember that revoking Rowset access does not remove a file after it has been downloaded.

### Can a public preview change Rowset rows?

No. Rowset public browser previews and the public Dataset API are read-only. Changes require an authenticated private path with a key that has sufficient permission.

### When should I create a separate dataset for sharing?

Create a separate dataset when the working schema contains private fields, internal instructions, or operational notes the audience should not see. A share-safe dataset acts as an allowlist and prevents future private columns from appearing automatically.

## The operating rule

Use this rule in an agent workflow:

```text
Before sharing Rowset data, identify the audience, allowed action, and access
lifetime. Use scoped MCP or REST for private live work, an authenticated export
for a snapshot, and a public preview only for deliberately shareable read-only
rows. Minimize the data, keep credentials secret, and perform the cleanup step.
```

If you want to try the pattern with a real workflow, start with a private [feedback triage dataset](/use-cases/feedback-triage), then create a reduced review dataset for the audience. Rowset's [pricing page](/pricing) covers the hosted trial and ongoing plan.
