import argparse
import json
import sys
from pathlib import Path

from .harness import (
    EvaluationError,
    build_run_matrix,
    evaluate_results,
    load_json,
    load_jsonl,
    render_report,
    run_adapters,
    validate_corpus,
    validate_results,
)

ROOT = Path(__file__).resolve().parent


def _write_jsonl(path, records):
    path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records))


def build_parser():
    parser = argparse.ArgumentParser(description="Compare Rowset agent interface conditions.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate corpus and optional results.")
    validate.add_argument("--results", type=Path)

    matrix = subparsers.add_parser("matrix", help="Write the client/condition/task matrix.")
    matrix.add_argument("--client", action="append", dest="clients", required=True)
    matrix.add_argument("--output", type=Path, required=True)

    run = subparsers.add_parser("run", help="Run cases through client adapter commands.")
    run.add_argument(
        "--adapter",
        action="append",
        required=True,
        help="Client and command in client=command form; repeat for each client.",
    )
    run.add_argument("--task", action="append", dest="tasks", default=[])
    run.add_argument("--run-id", required=True)
    run.add_argument("--timeout-seconds", type=int, default=300)
    run.add_argument("--output", type=Path, required=True)

    report = subparsers.add_parser("report", help="Score results and write a Markdown report.")
    report.add_argument("--results", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--baseline", type=Path)
    report.add_argument("--thresholds", type=Path, default=ROOT / "thresholds.json")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    corpus = load_json(ROOT / "corpus.json")
    try:
        validate_corpus(corpus)
        if args.command == "validate":
            if args.results:
                validate_results(load_jsonl(args.results), corpus)
            return 0
        if args.command == "matrix":
            matrix = build_run_matrix(corpus, args.clients)
            _write_jsonl(args.output, matrix)
            return 0
        if args.command == "run":
            adapters = {}
            for value in args.adapter:
                if "=" not in value:
                    raise EvaluationError("Adapters must use client=command form.")
                client, command = value.split("=", 1)
                if not client or client in adapters:
                    raise EvaluationError(f"Adapter client must be unique: {client or value}")
                adapters[client] = command
            results = run_adapters(
                corpus,
                adapters,
                args.tasks,
                args.run_id,
                timeout_seconds=args.timeout_seconds,
            )
            _write_jsonl(args.output, results)
            return 0
        results = load_jsonl(args.results)
        validate_results(results, corpus)
        thresholds = load_json(args.thresholds)
        baseline_results = load_jsonl(args.baseline) if args.baseline else None
        if baseline_results:
            validate_results(baseline_results, corpus)
        summary = evaluate_results(results, thresholds, baseline_results=baseline_results)
        args.output.write_text(render_report(summary))
        return 0 if summary["passed"] else 1
    except (EvaluationError, OSError) as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
