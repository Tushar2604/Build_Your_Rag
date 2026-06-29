"""Command-line entry point for the eval harness.

  # Run against the live RAG pipeline for a chatbot and print the scorecard:
  python -m evals.cli run --dataset evals/datasets/sample.jsonl \
      --tenant <tenant-uuid> --chatbot <chatbot-uuid> --judge

  # Promote a run to the committed baseline:
  python -m evals.cli run --dataset evals/datasets/sample.jsonl \
      --tenant ... --chatbot ... --out evals/baselines/sample.json

  # Gate a fresh run against the baseline (exit 1 on regression — use in CI):
  python -m evals.cli compare --dataset evals/datasets/sample.jsonl \
      --tenant ... --chatbot ... --baseline evals/baselines/sample.json
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from evals.dataset import GoldenDataset
from evals.regression import evaluate_regressions
from evals.report import EvalReport
from evals.runner import EvalRunner


async def _build_runner(args: argparse.Namespace) -> tuple[EvalRunner, GoldenDataset, str]:
    import uuid

    from src.config.container import get_container
    from src.domain.shared.identifiers import ChatbotId, TenantId

    from evals.judge import LLMJudge
    from evals.target import LiveTarget

    dataset = GoldenDataset.load_jsonl(args.dataset)
    tenant_id = TenantId(uuid.UUID(args.tenant))
    chatbot_id = ChatbotId(uuid.UUID(args.chatbot))
    target = await LiveTarget.for_chatbot(tenant_id, chatbot_id)

    judge = LLMJudge(get_container().llm) if args.judge else None
    runner = EvalRunner(target, k=args.k, judge=judge)
    return runner, dataset, f"chatbot:{args.chatbot}"


async def _cmd_run(args: argparse.Namespace) -> int:
    runner, dataset, target_name = await _build_runner(args)
    report = await runner.run(dataset, target_name=target_name)
    print(report.summary_table())
    if args.out:
        report.save(args.out)
        print(f"\nSaved report -> {args.out}")
    return 0


async def _cmd_compare(args: argparse.Namespace) -> int:
    runner, dataset, target_name = await _build_runner(args)
    current = await runner.run(dataset, target_name=target_name)
    print(current.summary_table(), "\n")

    verdict = evaluate_regressions(EvalReport.load(args.baseline), current)
    print(verdict.render())
    if args.out:
        current.save(args.out)
    return 0 if verdict.passed else 1


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dataset", required=True, help="Path to a .jsonl golden dataset")
    p.add_argument("--tenant", required=True, help="Tenant UUID")
    p.add_argument("--chatbot", required=True, help="Chatbot UUID to evaluate")
    p.add_argument("--k", type=int, default=5, help="top-k for retrieval metrics")
    p.add_argument("--judge", action="store_true", help="enable the LLM judge axes")
    p.add_argument("--out", help="optional path to write the JSON report")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals", description="RAG eval harness")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run the dataset and print a scorecard")
    _add_common(run_p)

    cmp_p = sub.add_parser("compare", help="run and gate against a baseline (CI)")
    _add_common(cmp_p)
    cmp_p.add_argument("--baseline", required=True, help="baseline report JSON to compare against")

    args = parser.parse_args(argv)
    # Fail fast (synchronously) on a missing baseline before standing up the
    # event loop, container, or running the dataset.
    if args.command == "compare" and not Path(args.baseline).exists():
        print(f"No baseline at {args.baseline}. Create one with `run --out {args.baseline}`.")
        return 2
    handler = {"run": _cmd_run, "compare": _cmd_compare}[args.command]
    return asyncio.run(handler(args))


if __name__ == "__main__":
    sys.exit(main())
