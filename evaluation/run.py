"""CLI: python evaluation/run.py --help"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
# This isolated evaluator does not send traces to an ambient observability project.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
from evaluation.common import write_report  # noqa: E402 (paths/env must be initialized first)


def parser():
    p = argparse.ArgumentParser(description="ReTrade 五层评测；默认隔离数据、offline，不修改业务源码")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("retrieval", "answers", "workflow", "reliability", "load"):
        q = sub.add_parser(name)
        q.add_argument("--mode", choices=["offline", "live"], default="offline")
        q.add_argument(
            "--allow-live", action="store_true", help="explicitly authorize paid model/embedding/rerank calls"
        )
        q.add_argument("--dataset", type=Path)
        q.add_argument("--limit", type=int, default=0)
        q.add_argument("--split", choices=["all", "dev", "test"], default="all")
        q.add_argument("--repeats", type=int, default=1)
        q.add_argument("--top-k", type=int, default=5)
        q.add_argument("--out", type=Path, default=ROOT / "evaluation/reports/latest")
        q.add_argument(
            "--fail-on-regression",
            action="store_true",
            help="exit 2 for rule failures; not a production approval",
        )
        if name == "retrieval":
            q.add_argument("--ks", nargs="+", type=int, default=[1, 3, 5])
            q.add_argument(
                "--strategies", nargs="+", choices=["hybrid", "bm25", "vector"], default=["hybrid"]
            )
            q.add_argument("--no-rerank", action="store_true")
        if name == "load":
            q.add_argument("--requests", type=int, default=10)
            q.add_argument("--concurrency", type=int, default=2)
            q.add_argument("--message", default="平台退货规则是什么？")
    q = sub.add_parser("business")
    q.add_argument("--input", type=Path)
    q.add_argument("--demo", action="store_true")
    q.add_argument("--as-of")
    q.add_argument("--window-hours", type=int, default=48)
    q.add_argument("--out", type=Path, default=ROOT / "evaluation/reports/business")
    q = sub.add_parser("score")
    q.add_argument("--input", required=True, type=Path)
    q.add_argument("--judge", action="store_true")
    q.add_argument("--ragas", action="store_true")
    q.add_argument("--allow-live", action="store_true")
    q.add_argument("--allow-fixture-score", action="store_true")
    q.add_argument("--limit", type=int, default=0)
    q.add_argument("--timeout", type=int, default=120)
    q.add_argument("--out", type=Path, default=ROOT / "evaluation/reports/scored")
    q = sub.add_parser("compare")
    q.add_argument("--baseline", required=True, type=Path)
    q.add_argument("--candidate", required=True, type=Path)
    q.add_argument("--out", type=Path, default=ROOT / "evaluation/reports/compare")
    q = sub.add_parser("review")
    q.add_argument("--input", required=True, type=Path)
    q.add_argument("--out", type=Path, default=ROOT / "evaluation/reports/review")
    sub.add_parser("validate")
    return p


def main():
    args = parser().parse_args()
    if getattr(args, "limit", 0) < 0 or getattr(args, "repeats", 1) < 1:
        raise ValueError("limit>=0, repeats>=1 required")
    if getattr(args, "top_k", 5) not in range(1, 21):
        raise ValueError("top-k must be 1..20")
    if args.command == "retrieval" and (
        any(k < 1 or k > args.top_k for k in args.ks) or len(set(args.strategies)) != len(args.strategies)
    ):
        raise ValueError("ks must be within 1..top-k; strategies must be unique")
    if args.command == "load" and (not 1 <= args.requests <= 1000 or not 1 <= args.concurrency <= 32):
        raise ValueError("requests 1..1000 and concurrency 1..32 required")
    if args.command == "load" and (args.repeats != 1 or args.dataset or args.limit or args.split != "all"):
        raise ValueError("load uses --requests/--concurrency; dataset, split, limit and repeats do not apply")
    if args.command == "business" and args.window_hours < 1:
        raise ValueError("window-hours must be positive")
    if args.command == "validate":
        from evaluation.validate import validate_all

        print(json.dumps(validate_all(), ensure_ascii=False, indent=2))
        return
    if args.command in ("retrieval", "answers", "workflow", "load"):
        from evaluation import runners

        report = asyncio.run(getattr(runners, args.command)(args))
    elif args.command == "reliability":
        from evaluation.reliability import reliability

        report = asyncio.run(reliability(args))
    elif args.command == "business":
        from evaluation.business import business

        report = business(args)
    elif args.command == "score":
        from evaluation.scoring import score

        report = asyncio.run(score(args))
    else:
        from evaluation.reporting import compare, review

        report = (compare if args.command == "compare" else review)(args)
    write_report(report, args.out)
    if getattr(args, "fail_on_regression", False) and any(
        r.get("passed") is False or r.get("error") for r in report.get("rows", [])
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, FileNotFoundError, ImportError) as exc:
        # No secrets/upstream body is emitted by these suite validation messages.
        print("Evaluation setup failed: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
