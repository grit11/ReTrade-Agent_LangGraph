"""Offline aggregation of explicit production outcomes; unknown is never success."""

from datetime import datetime, timedelta, timezone
import math
from evaluation.common import read_jsonl, ratio, latency, metadata, mean

SOURCES = {"customer_confirmed", "business_receipt", "human_review", "unknown"}


def timestamp(value):
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("Timestamps must include timezone")
    return d


def validate(rows, as_of, allow_demo):
    seen = set()
    if not rows:
        raise ValueError("No sessions supplied; provide real JSONL or explicit --demo")
    for row in rows:
        required = {
            "session_id",
            "customer_hash",
            "issue_id",
            "category",
            "started_at",
            "ended_at",
            "resolved",
            "resolution_source",
            "handoff",
            "handoff_required",
            "technical_failure",
            "synthetic",
        }
        if required - row.keys():
            raise ValueError("Missing session fields: " + ", ".join(sorted(required - row.keys())))
        for name in ("session_id", "customer_hash", "issue_id", "category"):
            if not isinstance(row[name], str) or not row[name].strip():
                raise ValueError(name + " must be a nonempty string")
        sid = row["session_id"]
        if sid in seen:
            raise ValueError("Duplicate session_id: " + sid)
        seen.add(sid)
        if not isinstance(row.get("synthetic"), bool):
            raise ValueError("synthetic must explicitly be true/false")
        if row["synthetic"] and not allow_demo:
            raise ValueError("Synthetic sessions require --demo")
        for name in ("resolved", "handoff_required", "technical_failure"):
            if row.get(name) is not None and type(row[name]) is not bool:
                raise ValueError(name + " must be boolean/null")
        if type(row.get("handoff")) is not bool:
            raise ValueError("handoff must be boolean")
        if row.get("resolution_source") not in SOURCES:
            raise ValueError("Invalid resolution_source")
        if row.get("resolved") is not None and row["resolution_source"] == "unknown":
            raise ValueError("Observed outcome needs explicit evidence source")
        if row.get("csat") is not None and (type(row["csat"]) is not int or not 1 <= row["csat"] <= 5):
            raise ValueError("csat must be 1..5/null")
        for name in ("cost_usd", "latency_ms"):
            if row.get(name) is not None and (
                type(row[name]) not in (int, float) or not math.isfinite(row[name]) or row[name] < 0
            ):
                raise ValueError(name + " must be finite nonnegative/null")
        start = timestamp(row["started_at"])
        if start > as_of:
            raise ValueError("Session starts after as_of")
        if row.get("ended_at"):
            end = timestamp(row["ended_at"])
            if end < start or end > as_of:
                raise ValueError("Invalid ended_at")
        if not row.get("customer_hash") or not row.get("issue_id"):
            raise ValueError("customer_hash and issue_id required")


def aggregate(rows, as_of, window_hours):
    n = len(rows)
    known = [r for r in rows if r.get("resolved") is not None]
    csat = [r["csat"] for r in rows if r.get("csat") is not None]
    labeled = [r for r in rows if r.get("handoff_required") is not None]
    should = [r for r in labeled if r["handoff_required"]]
    should_not = [r for r in labeled if not r["handoff_required"]]
    tech = [r for r in rows if r.get("technical_failure") is not None]
    costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    window = timedelta(hours=window_hours)
    first = []
    groups = {}
    for r in rows:
        groups.setdefault((r["customer_hash"], r["issue_id"]), []).append(r)
    for group in groups.values():
        group.sort(key=lambda r: timestamp(r["started_at"]))
        initial = group[0]
        if not initial.get("ended_at"):
            continue
        end = timestamp(initial["ended_at"])
        if end + window > as_of:
            continue
        repeat = any(end < timestamp(r["started_at"]) <= end + window for r in group[1:])
        first.append((initial, repeat))
    resolved = sum(r.get("resolved") is True for r in rows)
    return {
        "sessions": n,
        "verified_resolution_rate": ratio(sum(r["resolved"] for r in known), len(known)),
        "outcome_label_coverage": ratio(len(known), n),
        "unknown_outcomes": n - len(known),
        "verified_resolutions_over_all_sessions_lower_bound": ratio(resolved, n),
        "handoff_rate": ratio(sum(r["handoff"] for r in rows), n),
        "handoff_label_coverage": ratio(len(labeled), n),
        "required_handoff_recall": ratio(sum(r["handoff"] for r in should), len(should)),
        "unnecessary_handoff_rate_on_not_required": ratio(
            sum(r["handoff"] for r in should_not), len(should_not)
        ),
        "csat_response_rate": ratio(len(csat), n),
        "csat_mean_1_to_5": mean(csat),
        "technical_failure_rate": ratio(sum(r["technical_failure"] for r in tech), len(tech)),
        "technical_label_coverage": ratio(len(tech), n),
        "mature_first_contacts": len(first),
        "repeat_contact_rate": ratio(sum(repeat for _, repeat in first), len(first)),
        "first_contact_verified_resolution_rate": ratio(
            sum(r.get("resolved") is True and not repeat for r, repeat in first), len(first)
        ),
        "first_contact_ai_only_verified_resolution_rate": ratio(
            sum(r.get("resolved") is True and not repeat and not r["handoff"] for r, repeat in first),
            len(first),
        ),
        "latency": latency([r["latency_ms"] for r in rows if r.get("latency_ms") is not None]),
        "observed_total_cost_usd": sum(costs),
        "cost_coverage": ratio(len(costs), n),
        "cost_per_verified_resolution_usd": sum(costs) / resolved if resolved and len(costs) == n else None,
        "repeat_window_hours": window_hours,
    }


def business(args):
    from evaluation.common import DATA

    path = args.input
    if args.demo:
        path = path or DATA / "business_demo.jsonl"
    if not path:
        raise ValueError("business requires --input REAL.jsonl or --demo")
    rows = read_jsonl(path)
    as_of = timestamp(args.as_of) if args.as_of else datetime.now(timezone.utc)
    validate(rows, as_of, args.demo)
    report = aggregate(rows, as_of, args.window_hours)
    categories = sorted(set(r["category"] for r in rows))
    # Recontact is calculated globally only; category slices omit potentially cross-category followups.
    report["by_category"] = {
        k: {
            name: value
            for name, value in aggregate(
                [r for r in rows if r["category"] == k], as_of, args.window_hours
            ).items()
            if not name.startswith(("first_contact", "repeat_contact", "mature_first"))
        }
        for k in categories
    }
    report["limitations"] = (
        "Requires complete observation window and stable issue_id across channels. No answer/CSAT alone infers resolution. Unknown labels excluded with coverage. Cost null when incomplete."
    )
    meta = metadata(args, dataset=path)
    meta.update(
        mode="SYNTHETIC_DEMO" if any(r["synthetic"] for r in rows) else "production_records",
        as_of=as_of.isoformat(),
        outcome_source="explicit imported annotations/receipts, not inferred from chat text",
    )
    if args.demo:
        report["production_conclusion"] = "NONE: synthetic demonstration"
    return {"meta": meta, "summary": report, "rows": rows}
