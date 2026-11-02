import json
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from evaluation.scoring import Judgment, evaluate_row, summarize, METRIC_NAMES, Judge


def answer(**kwargs):
    return {
        "id": "1",
        "question": "退货期限？",
        "answer": "签收后7天内。",
        "reference": "签收后7天内。",
        "evaluation_domain": "knowledge",
        "answerable": True,
        "contexts": ["签收后7天内可申请退货。"],
        "result": {"status": "responded"},
        "tool_calls": [],
        "judge": {"status": "not_requested"},
        **kwargs,
    }


@pytest.mark.asyncio
async def test_scoring_failures_and_nan_preserve_coverage():
    class Broken:
        async def evaluate(self, row):
            raise TimeoutError()

        async def ascore(self, **kwargs):
            return SimpleNamespace(value=float("nan"))

    r = await evaluate_row(answer(), Broken(), {k: Broken() for k in METRIC_NAMES})
    summary = summarize([r], True, True)
    assert summary["judge"]["coverage"]["value"] == 0
    assert summary["judge"]["rubric_pass_among_scored"]["value"] is None
    assert summary["ragas"]["metrics"]["faithfulness"]["mean"] is None
    assert summary["ragas"]["metrics"]["faithfulness"]["coverage"]["denominator"] == 1


@pytest.mark.asyncio
async def test_unanswerable_and_order_are_not_given_fake_ragas_scores():
    for r in [answer(answerable=False), answer(evaluation_domain="order")]:
        result = await evaluate_row(r, metrics={k: object() for k in METRIC_NAMES})
        assert result["ragas"]["status"] == "not_applicable"


@pytest.mark.asyncio
async def test_missing_retrieval_stays_in_eligible_denominator():
    class Metric:
        async def ascore(self, **kwargs):
            return SimpleNamespace(value=0.5)

    r = await evaluate_row(answer(contexts=[]), metrics={k: Metric() for k in METRIC_NAMES})
    assert r["ragas"]["metrics"]["faithfulness"]["status"] == "blocked"
    assert r["ragas"]["metrics"]["answer_relevancy"]["value"] == 0.5
    assert summarize([r], False, True)["ragas"]["applicable"] == 1

    class NegativeCosine:
        async def ascore(self, **kwargs):
            return SimpleNamespace(value=-0.2)

    negative = await evaluate_row(answer(), metrics={"answer_relevancy": NegativeCosine()})
    assert negative["ragas"]["metrics"]["answer_relevancy"]["value"] == -0.2


def test_judge_schema_rejects_invalid_scale_and_coercion():
    for value in [0, 6, "5", True]:
        with pytest.raises(ValidationError):
            Judgment(
                correctness=value,
                completeness=5,
                relevance=5,
                groundedness=5,
                critical_error=False,
                explanation="fixture",
            )


@pytest.mark.asyncio
async def test_judge_uses_captured_evidence_and_parses_strict_json():
    from openai import AsyncOpenAI
    import httpx

    captured = []

    def respond(request):
        body = json.loads(request.content)
        captured.append(body)
        value = dict(
            correctness=5,
            completeness=4,
            relevance=5,
            groundedness=5,
            critical_error=False,
            explanation="fixture only",
        )
        return httpx.Response(
            200,
            json={
                "id": "mock",
                "object": "chat.completion",
                "created": 0,
                "model": "mock",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(value)},
                    }
                ],
            },
        )

    async with AsyncOpenAI(
        api_key="mock-only",
        base_url="https://fixture.invalid/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        r = await Judge(client, "mock").evaluate(answer())
    assert r["rubric_pass"] is True
    assert json.loads(captured[0]["messages"][1]["content"])["retrieved_contexts"] == answer()["contexts"]
