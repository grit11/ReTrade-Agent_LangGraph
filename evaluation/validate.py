from evaluation.common import ROOT, DATA, read_jsonl
from evaluation.metrics import norm
import re


def validate_all():
    counts = {}
    kb = norm((ROOT / "resources/knowledge/knowledge_base.md").read_text(encoding="utf-8-sig"))
    for file in ["knowledge.jsonl", "orders.jsonl", "workflows.jsonl", "reliability.jsonl"]:
        rows = read_jsonl(DATA / file)
        ids = [r["id"] for r in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate id in " + file)
        counts[file] = len(rows)
        for row in rows:
            if row["split"] not in ("dev", "test"):
                raise ValueError("Unknown split")
            for p in row.get("forbidden_patterns", []):
                re.compile(p)
            if file == "knowledge.jsonl":
                if row["answerable"] != bool(row["gold_evidence"]):
                    raise ValueError("Missing evidence label " + row["id"])
                for group in row["gold_evidence"]:
                    if not any(norm(x) in kb for x in group):
                        raise ValueError("Gold evidence not in corpus: " + row["id"] + " " + str(group))
            if file == "workflows.jsonl":
                for turn in row["turns"]:
                    if turn["action"] not in ("chat", "repeat", "resume", "restart"):
                        raise ValueError("Invalid action")
    knowledge = read_jsonl(DATA / "knowledge.jsonl")
    groups = {}
    for row in knowledge:
        groups.setdefault(row["group_id"], set()).add(row["split"])
    if any(len(s) > 1 for s in groups.values()):
        raise ValueError("Topic group leaks across splits")
    return {
        "status": "passed",
        "counts": counts,
        "knowledge_label_coverage": "all answerable cases have corpus-grounded spans",
        "warning": "Starter annotations still need business-owner review; string facts are proxies.",
    }
