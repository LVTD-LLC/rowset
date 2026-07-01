# Agent Eval Run Artifacts

`make agent-eval-seed EVAL-001` creates a timestamped run directory here with
`result.json` and `result.md`. The harness records the seed prompt, expected
files, required checks, current git SHA, changed-file placeholders, observed
checks, result status, and follow-up notes.

The first version is intentionally a human/agent-run wrapper. It does not invoke
an agent automatically; it makes each run measurable and comparable after the
agent or human has executed the seed task.

Example dry-run command:

```bash
make agent-eval-seed EVAL-001
```

When editing the harness itself, use a temporary run directory while testing:

```bash
uv run python scripts/agent-eval-seed.py EVAL-001 --runs-dir /tmp/rowset-agent-evals
```
