"""Paired report comparisons and human-review export."""

import csv
import json
from evaluation.common import metadata, digest


def read_report(path):
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value.get("meta"), dict) or not value.get("rows"):
        raise ValueError("Expected nonempty evaluation JSON report")
    return value


def row_key(row):
    return row["id"], row.get("repeat", 0), row.get("strategy", "")


def index_rows(rows):
    indexed = {row_key(r): r for r in rows}
    if len(indexed) != len(rows):
        raise ValueError("Duplicate paired row keys")
    return indexed


def numeric(value, prefix=""):
    out = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(numeric(v, prefix + "." + k if prefix else k))
    elif type(value) in (int, float):
        out[prefix] = value
    return out


def compare(args):
    base = read_report(args.baseline)
    candidate = read_report(args.candidate)
    if base["meta"].get("suite") not in ("retrieval", "answers", "workflow", "reliability", "score"):
        raise ValueError("Paired comparison supports retrieval/answers/workflow/reliability/score reports")
    for key in ("suite", "mode", "dataset_sha256", "knowledge_sha256", "split", "ks"):
        if base["meta"].get(key) != candidate["meta"].get(key):
            raise ValueError("Incomparable reports: different " + key)
    if not base["meta"].get("dataset_sha256"):
        raise ValueError("Dataset fingerprint required")
    if base["meta"]["suite"] == "score":
        for key in ("judge_model", "judge_prompt_sha256", "embedding_model", "scoring_options"):
            if base["meta"].get(key) != candidate["meta"].get(key):
                raise ValueError("Use the same scorer when comparing candidate systems: " + key)
    a = index_rows(base["rows"])
    b = index_rows(candidate["rows"])
    if set(a) != set(b):
        raise ValueError("Paired cases differ; use same IDs, repeats, strategies and selection")
    rows = []
    for key in a:
        x, y = a[key], b[key]
        if x.get("question") != y.get("question"):
            raise ValueError("Paired questions differ: " + key[0])
        regression = x.get("passed") is True and y.get("passed") is False
        judge_regression = (
            x.get("judge", {}).get("rubric_pass") is True and y.get("judge", {}).get("rubric_pass") is False
        )
        rows.append(
            {
                "id": key[0],
                "repeat": key[1],
                "strategy": key[2],
                "baseline_rule_passed": x.get("passed"),
                "candidate_rule_passed": y.get("passed"),
                "rule_regression": regression,
                "judge_rubric_regression": judge_regression,
                "critical_rule_regression": regression and y.get("risk") == "critical",
                "new_execution_error": not x.get("error") and bool(y.get("error")),
            }
        )
    x = numeric(base["summary"])
    y = numeric(candidate["summary"])
    deltas = {k: {"baseline": x[k], "candidate": y[k], "delta": y[k] - x[k]} for k in x.keys() & y.keys()}
    summary = {
        "paired_rows": len(rows),
        "unique_cases": len({r["id"] for r in rows}),
        **{
            k: sum(r[k] for r in rows)
            for k in (
                "rule_regression",
                "judge_rubric_regression",
                "critical_rule_regression",
                "new_execution_error",
            )
        },
        "numeric_deltas": dict(sorted(deltas.items())),
        "interpretation": "Descriptive paired comparison only; no significance or production gate. Inspect coverage before score means; repetitions are correlated.",
    }
    meta = metadata(args)
    meta.update(
        mode=base["meta"]["mode"],
        baseline_sha256=digest(args.baseline),
        candidate_sha256=digest(args.candidate),
        baseline_meta=base["meta"],
        candidate_meta=candidate["meta"],
    )
    return {"meta": meta, "summary": summary, "rows": rows}


def cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    value = str(value) if value is not None else ""
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


def review(args):
    report = read_report(args.input)
    if report["meta"].get("suite") not in ("answers", "score"):
        raise ValueError("Human review requires answers.json or score.json")
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "human_review.csv"
    fields = [
        "id",
        "repeat",
        "category",
        "question",
        "answer",
        "reference",
        "rubric",
        "contexts",
        "tool_calls",
        "human_correctness_1_to_5",
        "human_completeness_1_to_5",
        "human_relevance_1_to_5",
        "human_groundedness_1_to_5",
        "human_critical_error",
        "human_overall_pass",
        "reviewer",
        "comments",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        for row in report["rows"]:
            writer.writerow({key: cell(row.get(key, "")) for key in fields})
    meta = metadata(args)
    meta.update(mode=report["meta"]["mode"], source_report_sha256=digest(args.input))
    return {
        "meta": meta,
        "summary": {
            "rows": len(report["rows"]),
            "csv": str(path),
            "note": "Human labels intentionally blank; review is blind to Judge scores. Calibrate Judge against this rubric before setting release gates.",
        },
        "rows": [],
    }
