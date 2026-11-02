import pytest
from evaluation.metrics import evidence_metrics, text_checks, turn_checks
from evaluation.common import percentile, ratio


def test_evidence_units_ranking_and_duplicate_chunks():
    scores = evidence_metrics(["无关", "规则甲", "规则甲"], [["规则甲"], ["规则乙", "同义乙"]], 3)
    assert scores["evidence_unit_recall"] == 0.5
    assert scores["mrr"] == 0.5
    assert scores["annotated_chunk_precision"] == pytest.approx(2 / 3)
    assert scores["covered_units"] == 1  # duplicate chunks cannot inflate recall
    assert evidence_metrics([], [["规则甲"]], 5)["evidence_hit"] == 0


def test_fact_alternatives_and_missing_denominator():
    assert (
        text_checks({"required_facts": [["7天", "七天"], ["未使用"]]}, "七天内可退")["fact_coverage_proxy"]
        == 0.5
    )
    assert ratio(0, 0)["value"] is None
    assert percentile([1, 3, 5], 0.95) == pytest.approx(4.8)


def test_forbidden_attempts_count_even_when_tool_failed():
    checks = turn_checks({"forbidden_tools": ["refund"]}, {}, [{"name": "refund", "status": "error"}], [])
    assert checks[0]["passed"] is False


def test_tool_name_without_correct_arguments_does_not_pass():
    checks = turn_checks(
        {"tool_args": [{"name": "get_order", "args": {"order_id": "ours"}}]},
        {},
        [{"name": "get_order", "status": "completed", "args": {"order_id": "other"}}],
        [],
    )
    assert checks[0]["passed"] is False
