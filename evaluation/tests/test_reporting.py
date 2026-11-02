import json
from types import SimpleNamespace
import pytest
from evaluation.reporting import compare, cell


def report(path, dataset="same", cases=None):
    path.write_text(
        json.dumps(
            {
                "meta": {"suite": "answers", "mode": "offline", "dataset_sha256": dataset},
                "summary": {},
                "rows": cases or [{"id": "a", "repeat": 0, "passed": True}],
            }
        )
    )
    return path


def test_compare_rejects_different_datasets_or_selected_cases(tmp_path):
    a = report(tmp_path / "a.json")
    b = report(tmp_path / "b.json", dataset="changed")
    args = SimpleNamespace(command="compare", baseline=a, candidate=b)
    with pytest.raises(ValueError, match="dataset"):
        compare(args)
    report(b, cases=[{"id": "b", "repeat": 0}])
    with pytest.raises(ValueError, match="Paired cases"):
        compare(args)


def test_critical_regression_is_retained_even_when_aggregate_improves(tmp_path):
    a = report(
        tmp_path / "a.json",
        cases=[{"id": "a", "passed": True, "risk": "critical"}, {"id": "b", "passed": False}],
    )
    b = report(
        tmp_path / "b.json",
        cases=[{"id": "a", "passed": False, "risk": "critical"}, {"id": "b", "passed": True}],
    )
    r = compare(SimpleNamespace(command="compare", baseline=a, candidate=b))
    assert r["summary"]["critical_rule_regression"] == 1


def test_csv_formula_is_escaped():
    assert cell("=1+1") == "'=1+1"
