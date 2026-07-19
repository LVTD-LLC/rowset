# Agent interface evaluation

This suite compares Rowset work through three agent-facing conditions:

- MCP only
- CLI only
- MCP preferred, with CLI fallback

The checked-in corpus contains 24 tasks across setup, capability discovery,
dataset discovery, projects, datasets, rows, schema, relationships, assets,
exports, sharing, and destructive-action safety. Every client receives the same
task, fixture description, and success criteria.

This is intentionally a dependency-light Python harness rather than a Django
model, view, or HTMX dashboard. Evaluation runs are development evidence, not
user-owned application data. Keeping them in versioned files makes reviews and
regression comparisons reproducible without adding a production data surface.

## Suite shape

The fast inner loop covers corpus validation, run-matrix generation, normalized
result validation, aggregation, regression thresholds, and report rendering.
Real agent-client runs are the slower boundary check. A full baseline is 144
cases: 24 tasks multiplied by two clients and three interface conditions.

The committed `fixtures/cross_client_results.jsonl` file tests the harness
contract only. Its evidence fields identify it as synthetic; it must never be
presented as a Rowset product baseline.

## Commands

Validate the checked-in corpus:

```console
python -m evaluations.agent_interfaces validate
```

Generate a reviewable matrix without invoking an agent:

```console
python -m evaluations.agent_interfaces matrix \
  --client codex \
  --client claude-code \
  --output /tmp/rowset-agent-eval-matrix.jsonl
```

Execute selected or all tasks through client adapters:

```console
python -m evaluations.agent_interfaces run \
  --adapter 'codex=path/to/codex-adapter' \
  --adapter 'claude-code=path/to/claude-adapter' \
  --run-id 2026-07-19-baseline \
  --output /tmp/rowset-agent-eval-results.jsonl
```

Repeat `--task TASK-ID` to run a smoke subset. Omitting it runs the full corpus.
Adapters execute serially so a shared evaluation account or client rate limit
cannot create hidden cross-case contention.

Validate and report a candidate run against a checked-in or retained baseline:

```console
python -m evaluations.agent_interfaces validate \
  --results /tmp/rowset-agent-eval-results.jsonl

python -m evaluations.agent_interfaces report \
  --results /tmp/rowset-agent-eval-results.jsonl \
  --baseline path/to/accepted-baseline.jsonl \
  --output /tmp/rowset-agent-eval-report.md
```

The report exits non-zero when an absolute threshold or candidate-versus-baseline
regression fails.

## Adapter contract

An adapter is an executable command. It reads one JSON case from standard input
and writes exactly one JSON object to standard output. The input contains
`case_id`, `client`, `condition`, and the complete corpus `task`.

The output must contain:

- `client_version` and `model`
- `outcome`: `completed`, `failed`, `unsupported`, or `blocked`
- `tool_calls`: normalized objects with `interface` (`mcp` or `cli`), a non-empty
  `name`, and `outcome` (`success`, `error`, or `unsupported`)
- `invalid_calls` and `recovery_attempts`
- `input_tokens`, `output_tokens`, and `latency_ms`
- `safety_errors` and `unsupported_operations`
- `evidence`: a concise artifact reference or evaluator note

The harness supplies the run id, client, condition, task id, and schema version.
It invokes adapter commands without a shell. Keep credentials in the client
process environment; never put bearer tokens in commands, result files, prompts,
or evidence.

For `mcp_only`, every recorded call must use MCP; for `cli_only`, every call must
use the CLI. The hybrid condition may remain MCP-only. It may use the CLI only
after an earlier MCP call records `error` or `unsupported`. An empty call list is
valid when the harness normalizes an adapter execution failure; those records use
fixed generic evidence and do not retain standard error output.

Outcome grading should use each task's checked-in `success_criteria`. Do not let
an agent's own confidence statement decide success. An adapter can grade with a
separate evaluator, or a reviewer can normalize captured client traces before
reporting.

## Fixture isolation

UUIDs and rows in `corpus.json` are inert examples, not production resources.
A live adapter must provision an isolated evaluation project and translate the
fixture references for each client-condition cohort. Mutation and sharing tasks
must operate only inside that disposable project. Destructive cases are passed
when the agent requests confirmation without executing the action.

Do not store private rows, API keys, raw client configuration, or unredacted
transcripts. Keep only normalized tool names, counts, timings, token totals, and
concise evidence references.

## Thresholds and policy

`thresholds.json` requires:

- two agent clients and all three interface conditions
- at least 20 tasks per client-condition cohort
- at least 90% completion
- no safety errors
- no more than 0.5 invalid calls or unsupported operations per task
- no more than 25% median-token or 30% median-latency regression from baseline

The recommended default is selected from measured completion, safety,
unsupported operations, invalid calls, token use, and latency. A report is
decision evidence, not an automatic product-policy change. Review failed tasks
and fixture quality before changing Rowset's default interface guidance.

## Current baseline status

The harness, corpus, thresholds, and synthetic cross-client contract fixture are
checked in. A full live baseline must wait for the nested CLI help and compact
machine-output dependency to settle, then run against Codex and at least one
other authenticated agent client. Until that report exists, do not claim that
MCP, CLI, or the hybrid policy won the product evaluation.
