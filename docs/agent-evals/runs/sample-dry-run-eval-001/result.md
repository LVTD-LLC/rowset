# EVAL-001 Run sample-dry-run-eval-001

- Status: dry_run
- Agent: manual-or-agent
- Model: unknown
- Base SHA: `sample-base-sha`
- Head SHA: `sample-head-sha`

## Prompt

Make API and MCP row writes accept unambiguous whitespace, hyphen, underscore,
and case variants for choice values while storing the canonical schema choice.

## Changed Files

- TODO: record changed files after the run

## Required Checks

- make test -- apps/datasets apps/mcp_server -q
- make lint-python
- make format-check

## Observed Checks

- No observed checks recorded yet

## Checks Passed

- No passed checks recorded yet

## Checks Failed

- No failed checks recorded

## Follow-Up Notes

Sample dry-run artifact showing the structure committed by the harness.
