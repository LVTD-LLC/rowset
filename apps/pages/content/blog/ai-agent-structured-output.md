---
title: "AI Agent Structured Output: Validate Before You Store"
description: "Turn AI agent structured output into durable rows with JSON Schema, business validation, stable identity, staging, and verified writes."
published_at: 2026-08-03
updated_at: 2026-10-30
author: Rasul Kireev
keywords:
  - AI agent structured output
  - structured output for AI agents
  - JSON Schema AI agent
  - agent output validation
topics:
  - agent workflows
  - structured data
  - dataset operations
canonical_url: https://rowset.lvtd.dev/blog/ai-agent-structured-output
image: /static/vendors/images/logo.png
image_alt: Rowset logo
robots: index, follow
---

AI agent structured output is a model response constrained to a defined machine-readable shape,
usually JSON Schema. It makes an agent's result easier to parse, but it does not prove that the
values are true, authorized, unique, or safe to write. Treat structured output as a typed proposal
that must pass application checks before it becomes a durable row.

Use three separate gates:

1. **Shape gate:** Does the result match the declared output schema?
2. **Meaning gate:** Do the values satisfy source, identity, policy, and business rules?
3. **Write gate:** Can the system create or update the destination safely and verify the result?

This guide calls that sequence the **shape -> meaning -> write contract**. The separation matters
because a perfectly valid JSON object can still name the wrong customer, repeat an existing
record, use stale evidence, or request an operation the agent is not allowed to perform.

## In this guide

- [What structured output does](#what-structured-output-does)
- [Why schema-valid is not business-valid](#schema-valid-is-not-business-valid)
- [Design the output contract](#design-the-output-contract)
- [Run the shape gate](#run-the-shape-gate)
- [Run the meaning gate](#run-the-meaning-gate)
- [Stage the proposal](#stage-the-proposal)
- [Run the write gate](#run-the-write-gate)
- [Handle retries and schema changes](#handle-retries-and-schema-changes)
- [Use Rowset as the durable layer](#use-rowset)
- [Try the contract with one fictional proposal](#try-one-proposal)
- [Structured output FAQ](#structured-output-faq)

<a id="what-structured-output-does"></a>
## What does structured output do for an AI agent?

Structured output constrains the agent's final response to fields and types your program can
inspect. Instead of parsing prose such as "the customer is likely at risk," an application can
request an object with `customer_id`, `risk_level`, `reason`, and `evidence_refs`.

Current provider implementations expose this through JSON Schema or language-native schema tools.
The [Claude Agent SDK structured-output guide, checked August
2026](https://code.claude.com/docs/en/agent-sdk/structured-outputs) accepts JSON Schema, Zod, or
Pydantic definitions and returns a validated `structured_output` value after the agent workflow.
The [Gemini structured-output guide, checked August
2026](https://ai.google.dev/gemini-api/docs/structured-output) describes JSON Schema output for
data extraction, classification, and agentic workflows.

Structured output is useful at boundaries where software needs to decide what happens next:

| Boundary | Example output | Next deterministic action |
|---|---|---|
| Research agent -> review queue | claims, source URLs, confidence | Reject missing evidence |
| Support agent -> CRM proposal | customer ID, category, summary | Look up the customer before staging |
| Extraction agent -> catalog | SKU, price, currency, source version | Validate types and compare the current row |
| Triage agent -> task board | issue ID, priority, owner, reason | Enforce allowed states and ownership |
| Agent -> another agent | task ID, result status, artifact reference | Verify the referenced artifact exists |

The schema removes ambiguity about the message format. It does not remove ambiguity about the
world the message describes.

<a id="schema-valid-is-not-business-valid"></a>
## Why is schema-valid output not necessarily correct?

JSON Schema validates structure. It can require fields, constrain types, limit strings to an
enumeration, and reject unexpected properties. The [JSON Schema object reference, checked August
2026](https://json-schema.org/understanding-json-schema/reference/object) documents `properties`,
`required`, and `additionalProperties` for those checks.

It cannot establish that a claim matches its source, that an identifier belongs to the signed-in
account, or that an update is still appropriate. Google's Gemini documentation states the limit
plainly: schema-constrained output can guarantee syntactically correct JSON without guaranteeing
that its values are semantically correct.

Consider this schema-valid result:

```json
{
  "customer_id": "CUS-184",
  "status": "cancelled",
  "reason": "Customer requested cancellation",
  "source_ref": "ticket:921"
}
```

The object may match every declared type and enum while still being unsafe to apply. Ticket 921
could belong to another customer. The ticket may say "do not cancel." The customer may already
have renewed. The agent may have read an untrusted instruction embedded in the ticket. A valid
shape is evidence that parsing can proceed, not permission to mutate business state.

<a id="design-the-output-contract"></a>
## 1. Design the output contract around one decision

Start with the application decision the object will support. Keep the schema smaller than the
model's full reasoning process. A reviewable customer-status proposal might use:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "proposal_id": {
      "type": "string",
      "description": "Stable retry key for this exact proposed change"
    },
    "customer_id": {
      "type": "string",
      "description": "Existing customer key from the approved source"
    },
    "proposed_status": {
      "type": "string",
      "enum": ["active", "at_risk", "cancelled"]
    },
    "reason": {"type": "string", "minLength": 1, "maxLength": 500},
    "source_refs": {
      "type": "array",
      "minItems": 1,
      "items": {"type": "string"}
    },
    "source_version": {"type": "string"},
    "requires_review": {"type": "boolean"}
  },
  "required": [
    "proposal_id",
    "customer_id",
    "proposed_status",
    "reason",
    "source_refs",
    "source_version",
    "requires_review"
  ]
}
```

Use specific types and enums where the application has a real closed set. Add descriptions that
define business meaning, not instructions such as "be accurate." Reject unexpected fields when
the provider and schema dialect support that rule. Version the contract outside the model output
so a reviewer can tell which definition produced a proposal.

Do not ask one object to contain raw documents, chain-of-thought, credentials, and destination
fields. Keep sensitive evidence in its source system or a protected store and return stable
references. The final object should contain what the next control needs, not every token the agent
saw.

<a id="run-the-shape-gate"></a>
## 2. Run the shape gate in application code

Provider-side structured output is the first check, not the only parser. Validate the received
object again at your application boundary with the schema dialect and library you control.

The shape gate should answer deterministic questions:

- Is the response a complete JSON object rather than a refusal, timeout, or truncated stream?
- Are all required properties present?
- Do values have the declared types?
- Are enum, length, range, and array constraints satisfied?
- Are unexpected properties rejected?
- Is the output-contract version supported by this worker?

Treat validation failure as a typed error. Preserve a safe error code and run ID, then retry only
when the operation is safe to repeat. Do not silently coerce `"yes"` into `true`, discard unknown
fields, or invent missing identifiers. Those repairs can hide a contract mismatch between the
agent and the application.

Provider schema support is not identical. Gemini documents a supported subset of JSON Schema, and
other providers may impose their own nesting or keyword limits. Keep a provider-facing schema and
an authoritative application schema if necessary, then test that every provider output still
passes the authoritative validator.

<a id="run-the-meaning-gate"></a>
## 3. Run the meaning gate against current state

The meaning gate checks facts and policy that JSON Schema cannot know. It should read authoritative
systems after receiving the structured output and before authorizing a write.

Check at least:

1. **Identity:** Does `customer_id` resolve inside the current account and approved scope?
2. **Evidence:** Do the source references exist, and does `source_version` still match?
3. **Consistency:** Does the proposed value agree with the cited evidence?
4. **Freshness:** Has the destination or source changed since the agent formed the proposal?
5. **Policy:** May this agent propose this field and operation?
6. **Consequence:** Does the change require a human or a separate approval policy?

Separate machine-checkable rules from judgment. Software can prove that a SKU exists, a date is
not in the future, and a price uses an allowed currency. A reviewer may need to decide whether an
ambiguous message really authorizes cancellation. Record each result independently instead of
collapsing everything into `valid: true`.

Source content remains untrusted even when the source is approved. A ticket, page, email, or file
can contain instructions addressed to the agent. Those instructions cannot change the schema,
tool permissions, destination, approval policy, or source allowlist.

<a id="stage-the-proposal"></a>
## 4. Stage the structured output before changing the destination

For any meaningful write, store the result as a proposal first. A staging row turns an ephemeral
model response into something a validator, reviewer, retry worker, or second agent can inspect.

| Field | Purpose |
|---|---|
| `proposal_id` | Stable index and idempotency key |
| `output_contract_version` | Schema expected by the application |
| `agent_run_id` | Link to runtime evidence without copying it |
| `source_refs` and `source_version` | Evidence identity and freshness |
| `proposed_values` | Schema-valid agent result |
| `shape_status` | Validator result and safe error codes |
| `meaning_status` | Business-rule and evidence result |
| `review_status` | Pending, accepted, rejected, or superseded |
| `destination_key` | Stable business key to create or update |
| `write_status` | Not started, applied, uncertain, or verified |

Staging is especially useful when the model provider has already validated the output. It keeps
that success from being mistaken for authorization. The proposal can pass the shape gate and
still remain blocked at the meaning or review gate.

If your use case begins with a document or message that must become a destination record, the
[AI agent data-entry workflow](/blog/ai-agent-data-entry) covers source capture, mapping, approval,
and read-back in more detail.

<a id="run-the-write-gate"></a>
## 5. Run the write gate with stable identity and read-back

The write gate converts one accepted proposal into one destination operation. Resolve the
destination by a stable business key before deciding between create and update. Do not use row
position, search-result order, or a model-generated guess as identity.

For each accepted proposal:

1. Read the current destination by its stable key.
2. Compare current state with the values reviewed at the meaning gate.
3. Stop or supersede the proposal if relevant state changed.
4. Create or update only the approved fields.
5. Attach the same `proposal_id` as a correlation key where supported.
6. Read the destination back by stable key.
7. Compare the stored result with the accepted proposal.
8. Mark the write verified only after the comparison passes.

An API timeout after a write is not proof of failure. Read before replaying. If the destination
already contains the intended values for the same proposal, record success. If it contains a
different value, stop for reconciliation. The [idempotent agent-update
guide](/blog/idempotent-ai-agent-updates) covers this uncertain-write path.

<a id="handle-retries-and-schema-changes"></a>
## How should agents handle retries and output-schema changes?

Bind each proposal to the exact output-contract version, source version, and intended destination
operation. A retry with the same inputs should reuse the same `proposal_id`. A changed source,
schema, target, or proposed value should create a new proposal and supersede the old one.

Evolve contracts deliberately:

- Add optional fields before making them required.
- Keep old validators available while in-flight proposals still use them.
- Migrate staged proposals explicitly rather than reinterpreting them silently.
- Record which agent, prompt, mapping, and output contract produced each proposal.
- Test refusals, truncation, provider errors, unknown fields, stale evidence, duplicates, and
  uncertain writes.

Do not let a model improvise a migration. The application owns the contract, and the destination
owns its own schema. A provider-facing output schema can change independently from the
[dataset schema](/docs/design-schema), but the mapping between them must be versioned and tested.

<a id="use-rowset"></a>
## Where does Rowset fit in a structured-output workflow?

Rowset is a private structured-row backend for trusted agents. It does not generate or validate a
model provider's structured output for you. Use the agent SDK and your application validator for
the shape gate, then use Rowset to hold reviewable proposals or accepted operational rows.

A small setup can use two private datasets:

```text
output_proposals  index: proposal_id
customer_status   index: customer_id
```

Put the output-contract version, review rules, and allowed transitions in the proposal dataset's
instructions and metadata. Define semantic column types for the fields humans inspect. Use a
stable index for retry-safe lookup, connect through [hosted MCP](/docs/connect-mcp) when an agent
needs discoverable tools, or use the [Dataset API](/docs/dataset-api) from application code.

Keep provider credentials in the agent runtime, not in dataset rows. Keep both datasets private
unless a deliberate read-only public preview is part of the workflow. Rowset datasets are mutable,
so use a purpose-built immutable store as well when the workflow requires tamper-evident or
compliance-grade records.

<a id="try-one-proposal"></a>
## Try the contract with one fictional proposal

Before connecting a real customer system, test whether your worker can distinguish a valid shape
from permission to write. Use the JSON Schema above and this fictional proposal:

```json
{
  "proposal_id": "demo-status-001",
  "customer_id": "CUS-DEMO-184",
  "proposed_status": "at_risk",
  "reason": "Fictional support ticket requests a retention review",
  "source_refs": ["demo-ticket:921"],
  "source_version": "r3",
  "requires_review": true
}
```

For the exercise, define the authoritative fixture separately: ticket 921 belongs to
`CUS-DEMO-184`, revision `r3` is current, and no reviewer has accepted the proposal. These are
test inputs, not records Rowset or a model has looked up. Your application validator should produce
these outcomes:

1. **Original proposal:** shape passes; identity and revision match the fixture. Keep review
   pending and the customer write not started. `requires_review: true` does not mean approved.
2. **Change only `customer_id` to `CUS-DEMO-999`:** shape still passes, but the ticket belongs to
   someone else. Fail the identity check; do not change either customer's state.
3. **Change only `source_version` to `r2`:** shape still passes, but the evidence is stale.
   Block the write and obtain current evidence before forming a new proposal.
4. **Change only `requires_review` to the string `"true"`:** shape fails because the contract
   requires a boolean. Do not coerce it or send it to the customer-write path.

These cases exercise the application boundary, not a provider SDK or a live CRM integration.
They make Google's [application-validation requirement](https://ai.google.dev/gemini-api/docs/structured-output)
concrete without treating a schema pass as a business decision.

To keep the original pending proposal for inspection, connect a trusted agent through the
[private MCP setup](/docs/connect-mcp), then use the [save-one-row and separate read-back
workflow](/docs/work-with-rows). Reuse a confirmed private proposal dataset if you already have
one. Give the agent this narrow handoff:

```text
Save only the fictional demo-status-001 proposal in the private proposal dataset
I confirm. Inspect its actual headers and index first. Store the proposal JSON as
text if the dataset uses text cells, alongside contract version demo-v1,
shape_status passed, meaning_status passed, review_status pending, and write_status
not_started. Read the exact proposal index before creating it; stop on conflicting
contents. Fetch it again after saving and compare the stored fields. Do not create
or update any customer record, publish a preview, or store credentials.
```

Dataset instructions and status labels do not enforce those gates. Your executor owns them;
Rowset API-key permissions are account-wide, not per-dataset grants. A successful proposal
read-back confirms storage, not approval or a customer-state change. Once this exercise behaves
as expected, repeat it with one authorized real input and your actual validator before enabling
destination writes.

If this shape -> meaning -> write contract matches your workflow, you can [start a 7-day Rowset
trial](/pricing) and create the smallest private staging dataset first.

<a id="structured-output-faq"></a>
## AI agent structured output FAQ

### What is structured output for an AI agent?

Structured output is an agent result constrained to a machine-readable schema, commonly JSON
Schema. It gives application code predictable fields and types. It does not by itself verify the
truth, freshness, authorization, uniqueness, or safety of the values.

### Is JSON mode the same as structured output?

Not necessarily. JSON mode may guarantee valid JSON without requiring a specific object shape.
Schema-constrained output requires the result to match declared properties, types, and supported
constraints. Check the provider's current documentation because terminology and supported JSON
Schema features differ.

### Should an agent write structured output directly to a database?

Only for low-risk operations whose identity, authorization, validation, and retry behavior are
enforced outside the model. For consequential or ambiguous writes, stage the output as a proposal,
run business checks, obtain any required approval, then write and read the destination back.

### Do structured outputs prevent hallucinations?

No. They constrain format, not factual accuracy. A model can return a schema-valid but unsupported
claim or the wrong identifier. Require source references, verify them against current state, and
keep deterministic business rules outside the prompt.

### What should be the stable ID for a structured-output proposal?

Use a reproducible ID derived from the workflow, source item and version, output-contract version,
and intended destination operation. The same logical attempt should produce the same ID on retry.
A materially changed source or proposal should produce a new ID and supersede the old record.

## The operating rule

Treat AI agent structured output as a typed proposal, not a completed transaction: validate its
shape, verify its meaning against current evidence and policy, then apply one retry-safe write and
read the destination back.
