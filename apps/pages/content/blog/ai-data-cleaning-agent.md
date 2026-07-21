---
title: "AI for Data Cleaning: A Safe Agent Workflow"
description: "Use AI for data cleaning with a reversible workflow for raw rows, proposed changes, human review, validation, and controlled writes."
published_at: 2026-07-21
updated_at: 2026-07-21
author: Rasul Kireev
keywords:
  - AI for data cleaning
  - AI data cleaning
  - AI agent data cleaning
  - clean data with AI
topics:
  - agent workflows
  - data quality
  - dataset operations
canonical_url: https://rowset.lvtd.dev/blog/ai-data-cleaning-agent
image: /static/vendors/images/logo.png
image_alt: Rowset logo
robots: index, follow
---

Use AI for data cleaning by keeping the source dataset unchanged, asking the agent to propose field-level changes, sending ambiguous decisions to a reviewer, and publishing only validated values through stable row keys. The safe unit of work is not “clean this file.” It is “propose this exact change to this exact row, with a reason and a test.”

The workflow has seven steps:

1. Define the clean-data contract before the agent sees the rows.
2. Preserve a raw snapshot and choose a stable row identity.
3. Profile missing values, duplicates, formats, and allowed values.
4. Split deterministic fixes from judgment calls.
5. Record proposed changes instead of overwriting the source.
6. Review ambiguous or high-impact changes.
7. Publish, validate, and reconcile the cleaned dataset.

This guide calls that the **source -> proposal -> approval -> publish** loop. Each boundary has a different job: preserve evidence, make changes inspectable, control judgment, and verify the final state.

## Can AI clean data reliably?

AI can help classify messy values, infer likely mappings, explain anomalies, and draft transformation rules. It should not be the sole authority for deleting rows, merging people or companies, filling material facts, or changing identifiers.

Reliability comes from the workflow around the model. Deterministic code should handle transformations with an exact rule. The agent should handle interpretation and proposal generation. A person or policy should decide ambiguous, sensitive, or expensive changes. A validation layer should check the published result.

That division matters because “dirty data” covers different failure modes:

| Problem | Example | Best first control |
|---|---|---|
| Representation | `US`, `USA`, `United States` | deterministic mapping table |
| Missing value | blank `country_code` | explicit null rule; do not guess by default |
| Duplicate row | same source record imported twice | stable source ID and exact duplicate rule |
| Possible duplicate entity | `Acme Inc` and `Acme, Incorporated` | agent proposal plus review |
| Invalid type | `tomorrow` in a date column | schema validation and rejection |
| Conflicting facts | two phone numbers for one contact | source priority rule or human decision |
| Untrusted text | a note tells the agent to ignore its task | treat cell text as data, never authority |

The current pandas documentation distinguishes missing-value sentinels by data type and warns that ordinary equality comparisons do not provide one universal missing-value test ([pandas missing-data guide, checked July 2026](https://pandas.pydata.org/pandas-docs/stable/user_guide/missing_data.html)). Its duplicate-data guidance likewise separates identifying duplicates from dropping them ([pandas duplicate-data guide, checked July 2026](https://pandas.pydata.org/pandas-docs/stable/user_guide/indexing.html#duplicate-data)). Detection and correction are separate decisions. Keep that separation when an agent is involved.

## 1. Define the clean-data contract

Write acceptance criteria before asking the agent to inspect values. A useful contract names the schema, identity, allowed transformations, prohibited guesses, review conditions, and final checks.

For a supplier-contact dataset, the contract might say:

```text
Identity: supplier_id never changes.
Required: supplier_id, company_name, source_system.
Normalize: trim outer whitespace; lowercase email domains; use ISO alpha-2 country codes.
Do not infer: phone numbers, legal company names, or missing email addresses.
Possible duplicates: propose a match; never merge automatically.
Review: any company-name change or confidence below 0.95.
Publish: patch only approved fields, then read each changed row back by supplier_id.
```

Put the contract next to the data rather than leaving it in one chat. In Rowset, dataset instructions and semantic column descriptions give later agent runs the same rules. The [schema-design guide](/docs/design-schema) covers types and column meaning, while the [dataset-instructions guide](/blog/structure-dataset-instructions-ai-agents) covers allowed actions and escalation rules.

NIST's AI Risk Management Framework treats testing, evaluation, verification, and validation as lifecycle activities rather than a final checkbox ([NIST AI RMF and Resource Center, checked July 2026](https://airc.nist.gov/)). For data cleaning, that means defining the test before the transformation and repeating it after publication.

## 2. Preserve the raw source and stable identity

Never make the agent's first pass destructive. Keep the original file, export, or raw dataset unchanged. Record when it was captured, where it came from, and which version the cleaning run used.

Every source row also needs stable identity. Prefer an upstream key such as `supplier_id`, `ticket_id`, or `external_contact_id`. If the source has no durable key, generate one once and keep it through the proposal and clean datasets. Row order is not identity; sorting or filtering can change it.

This is the source boundary in the four-part loop. It lets you answer three questions after a bad cleanup:

- What value did the source contain?
- Which rule or proposal changed it?
- Which published row received the result?

The W3C PROV model represents provenance through entities, activities, agents, and derivation relationships ([W3C PROV-O Recommendation](https://www.w3.org/TR/prov-o/)). You do not need to implement the full ontology for a small cleaning job, but its core distinction is useful: the raw row is an entity, the cleaning run is an activity, the agent or reviewer is an actor, and the clean row is derived from the source.

For Rowset, read the [index-column decision guide](/blog/choose-index-column-agent-rows) before creating production rows. A stable index gives the agent an exact lookup and patch target across retries and later runs.

## 3. Profile the dataset before changing it

The agent should first produce a data-quality report, not a clean dataset. Profile each column and count each problem class.

At minimum, collect:

- row count and unique index count
- blank and null counts by column
- exact duplicate-row count
- duplicate-index count
- distinct values for controlled categories
- values that fail type or format checks
- minimum and maximum dates or numbers where meaningful
- candidate entity matches that require interpretation

Use code for facts the computer can calculate exactly. For a CSV, pandas can detect missing values with `isna()` and identify exact duplicate rows with `duplicated()`. Let the agent explain the profile, group anomalies, and draft rules, but do not ask the model to estimate counts from a truncated sample.

The profile becomes the baseline for final reconciliation. If the raw dataset contains 8,400 rows and the approved plan removes 12 exact duplicates, the clean dataset should contain 8,388 rows unless another explicit rule explains the difference. Numbers here are illustrative, not Rowset customer metrics.

## 4. Separate deterministic fixes from judgment calls

Move each proposed transformation into one of three lanes.

### Deterministic

The same input always produces the same output under a versioned rule. Examples include trimming outer whitespace, parsing a documented date format, or mapping a closed country-code table. Implement these transformations in code and test them with fixed examples.

### Agent-proposed

The change needs interpretation but can be reviewed. Examples include mapping free-text job titles to a taxonomy, choosing the likely company website from several candidates, or flagging possible duplicate entities. Require the source value, proposed value, reason, confidence, and rule version.

### Prohibited or human-only

The cost of a wrong answer is too high, or the available evidence is insufficient. Examples include inventing missing personal data, merging accounts with conflicting identifiers, changing financial facts, or deleting records because the agent calls them “irrelevant.”

This split keeps AI data cleaning useful without pretending every transformation is a model decision. If a regex or lookup table solves the problem, use it. Save the model for cases where language or context matters.

## 5. Record proposed changes in a reviewable dataset

Do not hide the cleaning plan in a transcript. Store one row per proposed field change:

| Field | Purpose |
|---|---|
| `change_id` | stable identity for the proposal |
| `source_row_id` | exact row to be changed |
| `field_name` | one bounded target field |
| `source_value` | original value or protected evidence reference |
| `proposed_value` | intended final value |
| `rule_id` | versioned transformation or policy |
| `reason` | short explanation |
| `confidence` | calibrated review signal, not proof |
| `decision` | pending, approved, rejected, or needs_info |
| `reviewer_id` | person or policy that decided |
| `run_id` | cleaning run that produced the proposal |

This is the proposal boundary. It turns a vague request into a diff that people and software can inspect.

Keep source values out of general logs when they contain personal or sensitive data. A protected reference or redacted value may be enough for the review queue. The [AI agent audit-trail guide](/blog/ai-agent-audit-trail) explains how to join runtime, authorization, and state-change evidence without copying every payload into one log.

Also treat every text field as untrusted input. A customer note, CSV cell, or imported document may contain instructions aimed at the model. OWASP lists prompt injection as a primary LLM risk, including indirect instructions embedded in external content ([OWASP LLM01:2025, checked July 2026](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)). Dataset content can inform a cleaning decision; it cannot override the cleaning contract, permissions, or reviewer boundary.

## 6. Review ambiguity and consequential changes

Review by risk, not by a random sample alone. Send a proposal to a person when it changes identity, merges records, deletes data, fills a material fact, has low confidence, conflicts with another source, or falls outside a tested rule.

A practical policy is:

- auto-approve deterministic rules that passed their test suite
- batch-review high-confidence, low-impact semantic mappings
- individually review merges, deletions, identifier changes, and sensitive fields
- reject proposals without a stable source row or a reason
- stop the run when duplicate identities or row counts violate the contract

The [human-in-the-loop AI agent guide](/blog/human-in-the-loop-ai-agents) shows how to bind an approval to an exact action and re-check current state before execution. That last check matters: a reviewer may approve a proposal after another process has already updated the source row.

## 7. Publish, validate, and reconcile

Publish only approved changes through exact keys. Patch absolute final values rather than relative instructions such as “fix the next duplicate.” If a request times out, read the keyed row before retrying. The [idempotent-update guide](/blog/idempotent-ai-agent-updates) provides the complete identity -> desired state -> confirmation pattern.

After publication, rerun the profile and compare it with the contract:

1. confirm every source identity maps to the expected clean identity
2. compare raw, removed, merged, and published row counts
3. verify required fields and allowed category values
4. confirm rejected proposals did not reach the clean dataset
5. read changed rows back and compare approved values
6. export the result and record its run, rule, and source versions

The clean dataset is not correct because the agent says the task succeeded. It is correct when independent checks show that the approved transformations produced the expected state.

## A worked Rowset pattern

Rowset does not read an arbitrary source, clean it automatically, or replace pandas. Your agent can read a CSV, spreadsheet, or upstream API with its own tools, then use Rowset as the private operational surface for the workflow.

Use three datasets:

1. `supplier_contacts_raw`: preserved source rows with a stable `supplier_id`
2. `supplier_contact_changes`: field-level proposals keyed by `change_id`
3. `supplier_contacts_clean`: approved current values keyed by `supplier_id`

Store the cleaning contract in dataset instructions. Use [hosted MCP](/docs/connect-mcp) when the agent benefits from tool and schema discovery, or the [Dataset API](/docs/dataset-api) when a script already speaks HTTP. The [row-operations guide](/docs/work-with-rows) lists exact read, create, patch, and verification paths.

Rowset's signed-in dataset page records recent mutations, including changed fields for row updates. Treat that as operational history, not rollback or an immutable compliance log. Preserve raw data and separate evidence when your recovery or assurance requirements are stronger.

When the cleaned rows are ready for another system, export them rather than exposing private write credentials. Rowset can provide CSV, Markdown, or Parquet output and optional read-only public previews, while authenticated MCP and REST remain the private mutation paths.

## AI data-cleaning checklist

- [ ] The raw source is preserved and versioned.
- [ ] Every row has a stable identity that survives sorting and retries.
- [ ] The cleaning contract names allowed, reviewed, and prohibited changes.
- [ ] Exact profiling runs before any mutation.
- [ ] Deterministic transformations are implemented and tested as code.
- [ ] Agent proposals record source value, target value, rule, reason, and run.
- [ ] Imported text is treated as untrusted data, not instruction authority.
- [ ] Merges, deletions, identifiers, and sensitive fields receive explicit review.
- [ ] Approved changes publish through exact keyed updates.
- [ ] Final counts, constraints, and changed rows are independently reconciled.
- [ ] Provenance and evidence are retained at the assurance level the workflow needs.

## FAQ

### What is AI data cleaning?

AI data cleaning uses a model or agent to detect anomalies, classify messy values, propose mappings, or explain quality problems. It works best inside a controlled pipeline where deterministic code handles exact transformations, people review ambiguous decisions, and validation checks the published result.

### Should an AI agent delete duplicate rows automatically?

Only when “duplicate” has an exact, tested definition and the source is recoverable. Identical imports with the same stable source ID may be safe to deduplicate. Similar names, emails, or addresses may represent different entities, so the agent should propose a merge for review rather than delete a row.

### How should an agent handle missing values?

Start with an explicit null policy per field. Leave unknown values blank unless a trusted source and approved rule support a fill. Do not let an agent invent contact details, identifiers, dates, prices, or other material facts merely to make a column complete.

### How do you verify AI-cleaned data?

Compare the final dataset with the pre-cleaning profile and approved change set. Check row counts, stable identities, required fields, allowed values, rejected proposals, and read-after-write results. Verification should be executable and independent of the agent's completion message.

### Can Rowset clean data automatically?

No. Rowset provides private structured datasets, schema and instructions, stable row identity, authenticated MCP and REST writes, exports, and operational change history. An agent or script performs the cleaning. Rowset can hold the raw rows, proposed changes, approvals, and verified clean state.

## The operating rule

Use AI for data cleaning as a proposal engine inside a reversible pipeline. Preserve the source, make every change addressable and reviewable, publish through stable keys, and prove the final state with deterministic checks. If you want to test that workflow with private agent-managed datasets, Rowset offers a [7-day hosted trial](/pricing).
