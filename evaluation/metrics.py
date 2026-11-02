"""Deterministic metrics. Text matching is a proxy, not semantic correctness."""

import re
from evaluation.common import ratio, mean


def norm(text):
    return re.sub(r"\s+", "", text).lower()


def fact_present(group, text):
    # Alternatives for ONE required fact; all groups are required.
    return any(norm(term) in norm(text) for term in group)


def evidence_metrics(contexts, gold, k):
    contexts = contexts[:k]
    matches = [{i for i, g in enumerate(gold) if fact_present(g, c)} for c in contexts]
    relevant = [bool(x) for x in matches]
    covered = set().union(*matches) if matches else set()
    first = next((i for i, yes in enumerate(relevant, 1) if yes), None)
    # Labels use gold evidence units; report precision as an annotated-evidence proxy.
    return {
        "evidence_hit": int(bool(covered)),
        "evidence_unit_recall": len(covered) / len(gold) if gold else None,
        "annotated_chunk_precision": sum(relevant) / len(contexts) if contexts else 0.0,
        "mrr": 1 / first if first else 0.0,
        "returned": len(contexts),
        "gold_units": len(gold),
        "covered_units": len(covered),
    }


def text_checks(case, reply):
    groups = case.get("required_facts", [])
    covered = [fact_present(g, reply) for g in groups]
    violations = [p for p in case.get("forbidden_patterns", []) if re.search(p, reply, re.I)]
    return {
        "fact_coverage_proxy": mean(covered),
        "fact_groups": len(groups),
        "missing_fact_groups": [g for g, ok in zip(groups, covered) if not ok],
        "forbidden_pattern_matches": violations,
        "all_fact_checks_pass": all(covered) and not violations
        if groups or case.get("forbidden_patterns")
        else None,
    }


def field(obj, path):
    for key in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def turn_checks(turn, result, calls, events):
    checks = []
    for path, expected in turn.get("expect", {}).items():
        actual = field(result, path)
        allowed = expected if isinstance(expected, list) else [expected]
        checks.append({"name": path, "expected": expected, "actual": actual, "passed": actual in allowed})
    names = [x["name"] for x in calls if x.get("status") == "completed"]
    for name in turn.get("required_tools", []):
        checks.append({"name": "tool:" + name, "passed": name in names})
    for name in turn.get("forbidden_tools", []):
        checks.append({"name": "forbidden_tool:" + name, "passed": not any(c["name"] == name for c in calls)})
    for expected in turn.get("tool_args", []):
        valid = any(
            c["name"] == expected["name"]
            and c.get("status") == "completed"
            and all(c.get("args", {}).get(k) == v for k, v in expected["args"].items())
            for c in calls
        )
        checks.append(
            {"name": "tool_args:" + expected["name"], "expected": expected["args"], "passed": valid}
        )
    for order in turn.get("ordered_tools", []):
        pos = -1
        ok = True
        for name in order:
            try:
                pos = names.index(name, pos + 1)
            except ValueError:
                ok = False
                break
        checks.append({"name": "ordered_tools", "expected": order, "passed": ok})
    for stage in turn.get("forbidden_stages", []):
        checks.append(
            {"name": "forbidden_stage:" + stage, "passed": not any(e.get("stage") == stage for e in events)}
        )
    tx = text_checks(turn, result.get("reply", ""))
    if tx["all_fact_checks_pass"] is not None:
        checks.append({"name": "reply_fact_proxy", "passed": tx["all_fact_checks_pass"], "detail": tx})
    return checks


def success_summary(rows):
    graded = [r for r in rows if r.get("passed") is not None]
    by_category = {}
    for r in rows:
        by_category.setdefault(r.get("category", "other"), []).append(r)
    return {
        "total": len(rows),
        "task_success": ratio(sum(r["passed"] for r in graded), len(graded)),
        "execution_errors": sum(bool(r.get("error")) for r in rows),
        "critical_case_failures": sum(r.get("risk") == "critical" and r.get("passed") is False for r in rows),
        "by_category": {
            k: ratio(sum(r.get("passed") is True for r in v), len(v)) for k, v in by_category.items()
        },
    }
