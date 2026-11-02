"""52 题评估入口的覆盖率、证据保留和断点续跑回归；不调用外部模型。"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_spec = importlib.util.spec_from_file_location(
    "rag52_runner", Path(__file__).resolve().parents[2] / "eval/run_eval.py"
)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def test_original_dataset_and_keyword_denominators():
    """原 52 题的五道无答案题不得进入关键词和 RAGAS 分母。"""
    rows = runner.load_dataset(runner.ROOT / "eval/datasets/qa.jsonl")
    assert len(rows) == 52
    assert sum(r["answerable"] for r in rows) == 47
    for row in rows:
        row["contexts"] = [" ".join(row["keywords"])]
        row["keyword_proxy_hit"] = runner.keyword_hit(row)
    summary = runner.report_summary(rows, 52, False, False)
    assert summary["keyword_baseline"]["hit_rate_all_known"] == runner.ratio(47, 47)
    assert sum(r["keyword_proxy_hit"] is None for r in rows) == 5


def test_resume_rejects_changed_configuration_and_retains_evidence(tmp_path):
    """报告保留回答与上下文，只允许相同实验配置续跑。"""
    out = tmp_path / "report.json"
    row = {"id": "sample", "answer": "回答", "contexts": ["证据"]}
    report = {"meta": {"status": "running", "run_signature": "original"}, "summary": {}, "rows": [row]}
    runner.write_report(report, out)
    with pytest.raises(ValueError):
        runner.resume_rows(out, "original", False)
    with pytest.raises(ValueError):
        runner.resume_rows(out, "changed", True)
    rows, _ = runner.resume_rows(out, "original", True)
    assert rows == [row]
    assert json.loads(out.with_suffix(".jsonl").read_text(encoding="utf-8")) == row


@pytest.mark.asyncio
async def test_resume_only_retries_failed_metrics():
    """评分失败重试不能覆盖成功的 Judge 或已经完成的 RAGAS 指标。"""
    class Metric:
        """返回固定分数并记录调用次数的异步指标替身。"""

        def __init__(self):
            """初始化调用计数器。"""
            self.calls = 0

        async def ascore(self, **kwargs):
            """模拟成功的指标请求。"""
            self.calls += 1
            return SimpleNamespace(value=0.8)

    row = {
        "question": "问题", "answer": "回答", "reference": "参考", "contexts": ["证据"],
        "answerable": True, "evaluation_domain": "knowledge", "judge": {"status": "ok"},
        "ragas": {"status": "partial_or_failed", "metrics": {
            "faithfulness": {"status": "ok", "value": 1.0},
            "context_recall": {"status": "error"},
        }},
    }
    done, missing = Metric(), Metric()
    scored = await runner.score_row(row, object(), {"faithfulness": done, "context_recall": missing}, 10)
    assert done.calls == 0 and missing.calls == 1
    assert scored["judge"] == row["judge"]
    assert scored["ragas"]["metrics"]["faithfulness"]["value"] == 1.0
    assert scored["ragas"]["metrics"]["context_recall"]["value"] == 0.8
    assert scored["ragas"]["status"] == "ok"


def test_dataset_rejects_duplicate_ids(tmp_path):
    """拒绝会在检查点字典中覆盖彼此的重复编号。"""
    path = tmp_path / "bad.jsonl"
    row = {"id": "same", "category": "类别", "question": "问题", "reference": "参考"}
    path.write_text((json.dumps(row) + "\n") * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        runner.load_dataset(path)
