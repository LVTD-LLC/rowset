# Agent Eval Run Artifacts

`make agent-eval-seed EVAL-001` creates a timestamped run directory here with
`result.json` and `result.md`. The harness records the seed prompt, expected
files, required checks, current git SHA, changed-file placeholders, observed
checks, result status, and follow-up notes.

The first version is intentionally a human/agent-run wrapper. It does not invoke
an agent automatically; it makes each run measurable and comparable after the
agent or human has executed the seed task.

When an existing run is overwritten with `--force`, the harness preserves the
existing `base_sha` unless `--base-sha` is provided. This lets a runner create a
dry-run artifact before an agent starts, then refresh `head_sha` after commits
without losing the original comparison point.

Example dry-run command:

```bash
make agent-eval-seed EVAL-001
```

When editing the harness itself, use a temporary run directory while testing:

```bash
uv run python scripts/agent-eval-seed.py EVAL-001 --runs-dir /tmp/rowset-agent-evals
```

## Rowset Writeback

`uv run python scripts/agent-eval-seed.py --print-rowset-schema` prints the
`create_dataset` payload for a private Rowset eval-results dataset. Create that
dataset through Rowset MCP, then pass `--rowset-dataset-key <dataset-key>` when
creating or refreshing a run artifact. The script upserts by `run_id`, so a
rerun refreshes the same Rowset row.

The API key must live in `ROWSET_API_KEY` by default. Use
`--rowset-api-key-env` if a different private environment variable holds the
key. Keep eval rows to summaries: no API keys, OAuth tokens, private dataset
contents, or full command logs.
