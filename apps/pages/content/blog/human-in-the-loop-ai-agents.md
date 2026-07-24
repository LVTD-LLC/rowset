---
title: "Human-in-the-Loop AI Agents: A Practical Workflow"
description: Build a human-in-the-loop AI agent workflow with risk-based approval gates, structured decisions, explicit ownership, and verified outcomes.
published_at: 2026-07-18
updated_at: 2026-07-18
author: Rasul Kireev
keywords:
  - human in the loop AI agents
  - AI agent approval workflow
  - human oversight for AI agents
  - AI agent review queue
topics:
  - human in the loop
  - agent workflows
  - approval systems
canonical_url: https://rowset.lvtd.dev/blog/human-in-the-loop-ai-agents
image: /static/vendors/images/logo.png
image_alt: Rowset logo
robots: index, follow
---

A human-in-the-loop AI agent workflow should pause before a consequential action, show a named reviewer the exact proposed change and its evidence, require an explicit decision, and verify the result after execution. Review belongs at risk boundaries, not on every agent step.

For delegated work that needs durable ownership, blockers, completion evidence, and a separate
review state, use the [AI agent task-management
contract](/blog/ai-agent-task-management) alongside the approval boundary in this guide.

The practical sequence is:

1. Classify the action by reversibility, blast radius, and external effect.
2. Let low-risk reads and drafts run automatically.
3. Write a stable approval record before a consequential action.
4. Show the reviewer the exact target, parameters, evidence, and likely consequence.
5. Approve, edit, reject, or let the request expire.
6. Re-read the decision and verify its scope before execution.
7. Record the outcome and reconcile ambiguous results before any retry.

This is the **boundary -> record -> decision -> reconcile** model. The boundary decides when autonomy stops. The record makes the proposal inspectable. The decision gives a human real authority. Reconciliation determines and records what happened when the target system exposes sufficient evidence. An uncertain result becomes `indeterminate` and escalates instead of being retried blindly.

## What is human-in-the-loop for AI agents?

Human-in-the-loop (HITL) means an AI agent must receive structured human input before it can continue past a defined workflow boundary. For a tool-using agent, that boundary is commonly a database write, deletion, payment, permission change, external message, publication, or another action that is costly to reverse.

That is different from post-hoc review. A weekly audit may find a bad action after the agent has already sent the email or deleted the record. HITL pauses before the effect. Human-on-the-loop monitoring is different again: a person watches an autonomous process and may intervene, but the agent does not necessarily stop for each decision.

| Oversight mode | When the human acts | Does the agent have to stop? | Best fit |
|---|---|---|---|
| Human-in-the-loop | Before a defined consequential action | Yes | Approval, correction, or escalation before execution |
| Human-on-the-loop | While an autonomous process runs | Not by default | Monitoring with the ability to intervene |
| Post-hoc review | After actions are complete | No | Auditing, evaluation, and policy improvement |

The useful question is not "Should this agent have a human in the loop?" It is "Which exact actions must stop, what must the reviewer see, and what evidence will prove that the approved action was the one executed?"

## A human approval button is not a safety system

Adding an Approve button does not guarantee a better outcome. A 2024 preregistered meta-analysis in *Nature Human Behaviour* examined 106 experiments. Human-AI combinations beat humans alone on average, but performed worse than the better of the human or AI acting alone; losses were concentrated in decision tasks, while creation tasks showed a more promising pattern. The lesson is to test the combined workflow instead of treating human presence as proof of safety ([Nature Human Behaviour, 2024](https://www.nature.com/articles/s41562-024-02024-1)).

Human presence also does not neutralize automation bias. Reviewers can over-rely on an automated recommendation, especially when the interface makes agreement easier than independent evaluation. A systematic review documented automation-bias errors across decision-support settings, although much of that evidence predates modern LLM agents ([Journal of the American Medical Informatics Association, 2012](https://pubmed.ncbi.nlm.nih.gov/21685142/)). Give reviewers evidence, consequences, and a real reject path rather than a ceremonial confirmation.

A reviewer can only make a real decision when the interface exposes the action clearly. Amazon Bedrock's HITL guidance distinguishes simple confirmation from return of control: confirmation shows the proposed function and parameter values before execution, while return of control lets the application or user modify the request before it is sent ([AWS, 2025](https://aws.amazon.com/blogs/machine-learning/implement-human-in-the-loop-confirmation-with-amazon-bedrock-agents/)).

NIST's AI Risk Management Framework puts the organizational half beside the interface: roles, responsibilities, communication lines, training, and accountable leadership need to be documented. A queue with no named owner is delayed automation, not oversight ([NIST AI RMF Core, checked July 2026](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)).

## Decide when an AI agent should ask for approval

Use deterministic policy before model judgment. The model can describe the action, but a rule should decide whether the action requires review whenever the risk can be expressed in advance.

| Action class | Default handling | Examples | Why |
|---|---|---|---|
| Read-only and bounded | Automatic | Read a known dataset, list ten tasks, validate a schema | No external state changes; ordinary authorization still applies |
| Reversible internal draft | Automatic, then inspect | Create a draft row, classify feedback, prepare a proposed status change | A person or later step can correct it before publication or external effect |
| Consequential write | Human approval | Change a customer-visible status, overwrite many rows, enable a public preview | The action changes shared state or widens access |
| External or costly effect | Human approval with exact parameters | Send a message, publish content, charge money, change permissions | The effect leaves the dataset or creates financial or reputational exposure |
| Destructive or out of policy | Deny or escalate | Archive a dataset, delete rows, expose sensitive data, bypass a required reviewer | Some actions should fail closed rather than offer a convenient approval button |

Three tests make the policy concrete:

- **Reversibility:** can the action be undone completely and cheaply?
- **Blast radius:** how many records, people, systems, or permissions can it affect?
- **External effect:** does it publish, communicate, charge, delete, or change access outside the agent's working state?

Repeated failure and ambiguity are review triggers too. If an agent calls the same tool several times without reaching a stable result, it should stop and show the attempts rather than improvise around the policy.

Do not require approval for every read. Constant prompts create approval fatigue and train reviewers to click through. Apply least privilege to the agent's credentials, then add approval only where authorization alone does not answer whether this specific action is appropriate.

AWS's current Agentic AI Lens recommends deterministic risk tiers, enough context for reviewers, timeout and escalation behavior, and audit records around critical decisions. Those controls belong in the workflow design rather than in an improvised prompt ([AWS Well-Architected, checked July 2026](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentsec04-bp02.html)).

## Store the proposed action as a durable record

A chat message is a weak approval record. It can disappear with the session, omit the exact parameters, or leave the executor unsure which version was approved. Store the proposal under a stable ID before asking for a decision.

This framework-neutral schema works for OpenAI Agents SDK, LangGraph, Microsoft Agent Framework, a custom MCP client, or a queue worker:

| Field | Purpose | Example |
|---|---|---|
| `approval_id` | Stable identity for the proposal | `APR-2026-0042` |
| `status` | Explicit lifecycle state | `pending`, `approved`, `rejected`, `superseded`, `expired`, `executed`, `failed`, `indeterminate` |
| `risk_tier` | Policy result that triggered the boundary | `consequential_write` |
| `policy_version` | Rule set that assigned the risk and boundary | `agent-actions-v3` |
| `agent_id` | Agent or runtime requesting the action | `content-agent-prod` |
| `tool_name` | Exact tool or operation | `enable_public_preview` |
| `target_resource` | Dataset, row, account, or external destination | `customer_feedback_review` |
| `proposed_parameters` | Normalized safe preview of the call | `public_enabled=true` |
| `action_hash` | Digest of canonical tool, target, parameters, actor, environment, and expiry | `sha256:...` |
| `supersedes_approval_id` | Link from a revised proposal to the record it replaces | `APR-2026-0041` |
| `evidence` | Sources, diff, tests, or context used | `review-checklist-184` |
| `requested_at` / `expires_at` | Decision window | ISO 8601 timestamps |
| `reviewer` / `reviewer_role` / `reviewed_at` | Authenticated ownership, authority tier, and decision time | `rasul`, `publisher`, timestamp |
| `authorization_evidence_id` | Signed decision or protected approval-service record bound to `action_hash` | `AUTH-9381` |
| `decision_reason` | Why it was approved, edited, or rejected | `Client review window confirmed` |
| `execution_id` / `idempotency_key` / `executed_at` | Claim and destination deduplication context | `EXEC-7781`, key, timestamp |
| `outcome` / `reconciliation_status` | Verified result, known failure, or unresolved effect | `Preview enabled; URL checked`, `confirmed` |

The status field should be a small controlled vocabulary, not free text. The proposal should be immutable in meaning after approval: if the target or parameters change, create a new approval ID. Otherwise an executor can receive approval for one action and perform another under the same record.

Use these transitions as application invariants:

| Current state | Allowed next state | Authorized actor | Invariant |
|---|---|---|---|
| `pending` | `approved`, `rejected`, `superseded`, `expired` | Authenticated approval service | Target and canonical action hash still match what the reviewer saw |
| `approved` | `executed`, `failed`, `indeterminate`, `expired` | Serialized executor | Executor claims the exact approval under locking or idempotency controls |
| `rejected`, `superseded`, `expired`, `executed`, `failed`, `indeterminate` | None | None | A retry or revision receives a new approval ID |

An Edit action therefore marks the old proposal `superseded` and creates a revised `pending` proposal with a new ID and `supersedes_approval_id`. It does not rewrite the meaning of the old proposal and keep its approval.

Do not put raw secrets in `proposed_parameters`, evidence, or outcomes. Store a safe description such as `credential=mailgun-production` rather than the credential value.

## Build a human-in-the-loop queue with Rowset

Rowset can act as the private structured-state layer for this workflow. It gives a trusted agent authenticated [MCP access](/docs/connect-mcp) or a [Dataset API](/docs/dataset-api), stable indexed rows, semantic column descriptions, choice values, and persistent dataset instructions.

Rowset is not the authorization engine that pauses your agent. The agent runtime or application must enforce the stop, collect the human decision, and refuse an execution that does not match the approved action. Rowset stores the proposal and decision so the workflow remains inspectable across sessions and frameworks.

Use a dedicated Rowset key with the smallest sufficient role. Current key permissions are account-level `read`, `read_write`, or `admin` privileges; they are not scoped to one dataset, row, or field. The application still needs to restrict which approval queue and protected tools that credential may operate.

Do not treat `status=approved` written with the proposing agent's own Rowset key as proof that a human approved anything. For consequential actions, authenticate the reviewer in the agent runtime or application, bind that decision to the proposal ID and parameters, and let a separate trusted process mirror the decision into Rowset. The Rowset row is coordination state; the reviewer's authenticated decision remains the authorization evidence.

### 1. Create a private approvals dataset

Use `approval_id` as the index column and add the fields from the table above. Configure `status` and `risk_tier` as choice columns so the agent sees the allowed vocabulary. The [schema design guide](/docs/design-schema) covers index selection, semantic types, descriptions, and choice values.

Choice values can reject an unknown status label, but Rowset does not enforce the lifecycle itself. Immutability after approval, allowed state transitions, reviewer authority, and expiry are application rules that the runtime must check.

Keep the dataset private. Approval records may contain customer names, unpublished actions, internal targets, and failure details. A Rowset public preview is a deliberate read-only sharing surface, not an authentication mechanism or approval channel.

### 2. Put the transition rules in dataset instructions

Instructions give future agents that inspect the dataset a consistent operating contract:

```text
Use approval_id as the stable index.
Create proposals with status=pending before any consequential action.
Never set reviewer, reviewed_at, status=approved, or status=executed based only on your own judgment.
Treat explicit user authorization for this approval_id as the decision source.
If target_resource or proposed_parameters changes, mark the old proposal superseded and create a new ID.
Before execution, read the row again and verify status, target, parameters, and expires_at.
After an ambiguous response, reconcile the external state before retrying.
Never store credentials or sensitive token values in this dataset.
```

Instructions guide agent behavior; they are not server-enforced approval policy. The runtime still needs a hard interrupt around the protected tool. Read [how to structure dataset instructions for AI agents](/blog/structure-dataset-instructions-ai-agents) for a fuller pattern that combines purpose, identity, allowed values, write rules, and escalation.

### 3. Create the pending record before notifying a reviewer

The agent normalizes the proposed action, writes the pending row, reads it back by `approval_id`, and then sends the review request through the runtime's approval interface. Writing first prevents the notification from pointing to state that was never persisted.

With Rowset MCP, the concrete sequence uses `create_dataset_row`,
`get_dataset_row_by_index`, and `update_dataset_row_by_index`. A REST client uses
the row collection plus the by-index read and patch endpoints. The runtime's
interrupt sits between the initial read and the decision update:

```text
create_dataset_row(approval_id=APR-2026-0042, status=pending, ...)
get_dataset_row_by_index(APR-2026-0042)
pause_runtime_and_request_human_decision()

auth_evidence = trusted_approval_service_records_signed_decision(APR-2026-0042, action_hash)
trusted_approval_service_updates_row(APR-2026-0042, status=approved, authorization_evidence_id=auth_evidence.id, ...)
approval = get_dataset_row_by_index(APR-2026-0042)
assert_signed_evidence_exact_scope_expiry_and_execution_policy(approval, auth_evidence)
claim_with_lock_or_idempotency_key_then_execute(approval)
update_dataset_row_by_index(APR-2026-0042, status=executed, outcome=...)
```

The [row operations guide](/docs/work-with-rows) documents the current MCP tool
names and REST paths. The interrupt and executor checks are application logic,
not Rowset calls.

The review card should show:

- the exact action and target
- a readable diff or normalized parameter list
- the risk reason that triggered review
- evidence and validation results
- the expected consequence and recovery plan
- the expiry time
- Approve, Edit, and Reject choices, plus a separate escalation path when no authorized reviewer is available

An ornamental confidence score is not enough. Reviewers need the underlying evidence and authority to change or stop the action. Across the 2024 meta-analysis, explanations and confidence information alone did not significantly improve combined performance on average; specific interfaces still need their own evaluation ([Nature Human Behaviour, 2024](https://www.nature.com/articles/s41562-024-02024-1)).

### 4. Persist the human decision

The reviewer makes the decision in the agent runtime, application, or another controlled interface. A trusted process then updates the Rowset record with the reviewer, decision time, reason, and final approved parameters. The proposing agent must not be able to manufacture the authorization evidence merely by patching its own queue row.

If another person only needs to inspect a sanitized queue, Rowset can expose a read-only, optionally password-protected preview. Use the [safe data-sharing decision guide](/blog/share-ai-agent-data-safely) before enabling it. The preview can support review, but it cannot submit the approval.

### 5. Re-read and verify before execution

The executor must load the approval record again rather than trust a stale in-memory object. Confirm all of these conditions:

- `status` is `approved`
- the proposal has not expired
- the reviewer is allowed to approve this risk tier
- `tool_name`, `target_resource`, and `proposed_parameters` exactly match the pending call
- `authorization_evidence_id` resolves to a protected decision bound to the same `action_hash`
- no `execution_id` already exists
- the current external state still permits the action

OWASP's AI Agent Security guidance recommends explicit tool authorization, separation between the decision and execution paths, binding approval to the exact action, expiry and replay protection, least privilege, and idempotency for side effects ([OWASP, checked July 2026](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html)). The approval row supports those checks; the executor must enforce them.

A re-read followed by execution is not an atomic compare-and-set operation. If two workers can execute the same approval concurrently, use an external lock, transactional claim, or destination idempotency key. Checking `execution_id` in Rowset reduces accidental replay but does not provide a cross-system exactly-once guarantee.

### 6. Record and reconcile the outcome

After execution, patch the record to `executed` with a safe result summary and timestamp. If the call times out, do not immediately replay it. Inspect the target system or Rowset row to determine whether the first call succeeded. Mark the outcome `indeterminate` when sufficient evidence is unavailable, then escalate instead of guessing or retrying.

The guide to [idempotent AI-agent updates](/blog/idempotent-ai-agent-updates) explains the identity -> desired state -> confirmation contract for Rowset rows. External payments, messages, and jobs need the destination system's own idempotency or deduplication contract.

Rowset's signed-in dashboard records recent dataset changes with actor labels and timestamps; row updates include before-and-after field details ([Rowset source](https://github.com/LVTD-LLC/rowset/blob/main/apps/api/row_mutations.py)). An actor label is the API-key name or generic `Account`, not verified proof of a natural person's identity. That history is useful for investigating a workflow, but it is not rollback, tamper-evident logging, nonrepudiation, or a compliance-grade audit system. It is currently a dashboard surface rather than an MCP or REST history endpoint.

The [AI agent audit trail guide](/blog/ai-agent-audit-trail) shows how to join
that business-state history to runtime traces and authorization records while
keeping Rowset's operational-history limits explicit.

## How agent frameworks pause and resume

The storage model is portable even though runtimes implement the interrupt differently.

- **OpenAI Agents SDK:** tools can require approval, interrupted runs expose pending approvals, and serialized run state can resume after decisions are supplied ([OpenAI Agents SDK, checked July 2026](https://openai.github.io/openai-agents-python/human_in_the_loop/)).
- **Microsoft Agent Framework:** request ports let a workflow emit an external request, wait, and route the response back to the executor that requested it ([Microsoft Learn, updated July 2026](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop)).
- **LangGraph or another checkpointed runtime:** interrupt before the protected tool, persist the framework checkpoint, and resume only after the approval record passes the executor's checks ([LangChain HITL docs, checked July 2026](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)).
- **Custom MCP agent:** wrap high-risk MCP tool calls with a policy layer. The agent may use Rowset MCP for the approvals dataset, but the protected tool wrapper must stop the side effect until an exact approval exists.

The framework checkpoint and approval row solve different problems. The checkpoint preserves where execution paused. The approval row preserves what was proposed, who decided, and what happened afterward.

## Prevent approval fatigue and rubber-stamping

Approval quality falls when every routine action looks urgent. Reduce the queue before trying to make the review screen faster.

1. Auto-approve bounded reads and reversible drafts under clear policy.
2. Batch related low-risk proposals when one decision can safely cover the exact set.
3. Escalate destructive, external, ambiguous, or high-blast-radius actions.
4. Expire stale proposals instead of leaving them available indefinitely.
5. Track rejection, edit, expiry, and time-to-decision rates by action class.
6. Review false-positive gates that humans always approve without changes.
7. Never create a permanent trust rule from one approval unless the human explicitly chose that scope.

NIST's AI RMF Playbook recommends histories and audit logs plus measurement of overrides, errors, complaints, escalations, adjudication, and go/no-go decisions. Those fields turn HITL from a reassuring label into a workflow you can inspect and improve ([NIST AI RMF Playbook, checked July 2026](https://airc.nist.gov/airmf-resources/playbook/measure/)).

## Handle failure states explicitly

### No reviewer responds

Expire the request and fail closed. Notify or reassign according to a documented escalation policy. Do not convert silence into approval.

### The reviewer edits the proposal

Treat the edit as a new exact action with a new approval ID. Mark the old proposal `superseded`, link the new proposal through `supersedes_approval_id`, and require a fresh decision on the revised target and parameters.

### The reviewer rejects the action

Store the reason, mark the proposal `rejected`, and prevent the agent from retrying the same action under different wording. A revised proposal needs a new ID and must explain what changed.

### Execution times out

Keep the original `execution_id` and reconcile the target before retrying. A lost response does not prove the side effect failed.

### The target changes while approval is pending

Invalidate the proposal when the current state no longer matches the evidence the reviewer saw. Recompute the diff and request a new decision.

## Production checklist

- [ ] Protected actions are defined by deterministic risk rules.
- [ ] The agent has the smallest useful credential permission.
- [ ] Every proposal has a stable ID, exact target, normalized parameters, and expiry.
- [ ] The review card shows evidence, consequence, and recovery instead of relying on a model explanation.
- [ ] A named reviewer owns each queue and escalation path.
- [ ] Pending, approval, rejection, supersession, expiry, execution, failure, and indeterminate outcomes are distinct states.
- [ ] The executor re-reads and binds approval to the exact action.
- [ ] Duplicate execution is prevented or reconciled with idempotency controls.
- [ ] Sensitive values are excluded from records and notifications.
- [ ] Outcomes, overrides, rejection reasons, and review latency are measurable.
- [ ] Change history is not described as rollback or compliance certification.
- [ ] The combined human-agent workflow is tested against a useful baseline.

If you need a private structured state layer for this pattern, start with the Rowset [quickstart](/docs/quickstart) or review [pricing](/pricing). Use the hosted product when you want the fastest setup; Rowset is also [open source](https://github.com/LVTD-LLC/rowset) and self-hostable when your team needs to operate the service itself.

## FAQ

### When should an AI agent ask for human approval?

Require approval before destructive, externally visible, financially consequential, permission-changing, high-blast-radius, or ambiguous actions. Let bounded reads and reversible internal drafts proceed automatically under least privilege. Also stop after repeated failures or when the agent cannot prove that a prior attempt succeeded.

### What should an AI agent approval request contain?

Show a stable proposal ID, exact tool, target, normalized parameters or diff, risk reason, evidence, expected consequence, recovery plan, and expiry. The reviewer should be able to approve, edit, reject, or escalate. Never include raw credentials or unnecessary sensitive data.

### How does an AI agent pause and resume after approval?

The runtime interrupts before the protected tool and persists its checkpoint. After the human decision, the executor reloads the approval record, verifies its scope and expiry, claims execution under locking or destination idempotency controls, records the outcome, and resumes the workflow from the checkpoint.

### Is human-in-the-loop the same as an audit log?

No. HITL controls whether a workflow may continue before an action. An audit or change history records what happened. A reliable system often needs both, but a history cannot undo an unapproved action and an approval button does not prove which action executed.

### Can Rowset enforce that only a human approves an action?

No. Rowset can store private approval records, instructions, structured decisions, and change history. Your agent runtime or application must authenticate the reviewer, enforce the pause, bind the decision to the exact action, and control execution.
