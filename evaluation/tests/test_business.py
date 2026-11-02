from copy import deepcopy
import pytest
from evaluation.business import aggregate, validate, timestamp


def row(**kwargs):
    return {
        "session_id": "1",
        "customer_hash": "hash1",
        "issue_id": "issue1",
        "category": "order",
        "synthetic": False,
        "started_at": "2026-09-10T00:00:00Z",
        "ended_at": "2026-09-10T00:05:00Z",
        "resolved": None,
        "resolution_source": "unknown",
        "handoff": False,
        "handoff_required": None,
        "technical_failure": None,
        "csat": None,
        "cost_usd": None,
        "latency_ms": None,
        **kwargs,
    }


AS_OF = timestamp("2026-09-16T00:00:00Z")


def test_unknown_is_not_resolved_and_missing_cost_is_not_free():
    records = [
        row(),
        row(
            session_id="2",
            customer_hash="hash2",
            issue_id="issue2",
            resolved=True,
            resolution_source="business_receipt",
            cost_usd=0.02,
        ),
    ]
    validate(records, AS_OF, False)
    m = aggregate(records, AS_OF, 48)
    assert m["verified_resolution_rate"]["value"] == 1
    assert m["outcome_label_coverage"]["value"] == 0.5
    assert m["verified_resolutions_over_all_sessions_lower_bound"]["value"] == 0.5
    assert m["cost_per_verified_resolution_usd"] is None
    assert m["csat_mean_1_to_5"] is None


def test_mature_window_and_cross_channel_repeat():
    first = row(resolved=True, resolution_source="human_review")
    repeat = row(session_id="2", started_at="2026-09-11T00:00:00Z", ended_at="2026-09-11T00:05:00Z")
    immature = row(
        session_id="3",
        customer_hash="hash2",
        issue_id="issue2",
        started_at="2026-09-15T00:00:00Z",
        ended_at="2026-09-15T00:05:00Z",
        resolved=True,
        resolution_source="human_review",
    )
    m = aggregate([first, repeat, immature], AS_OF, 48)
    assert m["mature_first_contacts"] == 1
    assert m["repeat_contact_rate"]["value"] == 1
    assert m["first_contact_verified_resolution_rate"]["value"] == 0


@pytest.mark.parametrize(
    "updates",
    [
        {"cost_usd": float("nan")},
        {"synthetic": True},
        {"resolved": True},
        {"csat": 6},
        {"started_at": "2026-09-10T00:00:00"},
    ],
)
def test_invalid_records_rejected(updates):
    with pytest.raises(ValueError):
        validate([row(**updates)], AS_OF, False)


def test_duplicate_session_rejected():
    with pytest.raises(ValueError):
        validate([row(), deepcopy(row())], AS_OF, False)
