"""Real installed RAGAS / Instructor / OpenAI adapter; HTTP is fully mocked."""

import json
import pytest


@pytest.mark.asyncio
async def test_four_ragas_metrics_through_actual_adapters():
    pytest.importorskip("ragas")
    import httpx
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.embeddings import OpenAIEmbeddings
    from evaluation.scoring import ragas_metrics, evaluate_row

    calls = []
    outputs = {
        "StatementGeneratorOutput": {"statements": ["签收后7天内可申请退货。"]},
        "NLIStatementOutput": {
            "statements": [{"statement": "签收后7天内可申请退货。", "reason": "fixture", "verdict": 1}]
        },
        "AnswerRelevanceOutput": {"question": "退货期限？", "noncommittal": 0},
        "ContextPrecisionOutput": {"reason": "fixture", "verdict": 1},
        "ContextRecallOutput": {
            "classifications": [
                {"statement": "签收后7天内可申请退货。", "reason": "fixture", "attributed": 1}
            ]
        },
    }

    def respond(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            values = body["input"]
            n = (
                len(values)
                if isinstance(values, list) and (not values or isinstance(values[0], (str, list)))
                else 1
            )
            calls.append("embedding")
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "mock",
                    "data": [
                        {"object": "embedding", "index": i, "embedding": [1.0, 0.0, 0.0]} for i in range(n)
                    ],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                },
            )
        # RAGAS 0.4.3's OpenAI Instructor adapter uses JSON mode, not tool mode.
        prompt = json.dumps(body["messages"], ensure_ascii=False)
        name = next(name for name in outputs if name in prompt)
        calls.append(name)
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
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(outputs[name], ensure_ascii=False),
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    async with AsyncOpenAI(
        api_key="mock-only",
        base_url="https://fixture.invalid/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        metrics = ragas_metrics(
            llm_factory("mock", client=client, temperature=0, max_retries=2),
            OpenAIEmbeddings(client=client, model="mock"),
        )
        r = await evaluate_row(
            {
                "question": "退货期限？",
                "answer": "签收后7天内可申请退货。",
                "reference": "签收后7天内可申请退货。",
                "contexts": ["签收后7天内可申请退货。"],
                "answerable": True,
                "evaluation_domain": "knowledge",
                "result": {"status": "responded"},
            },
            metrics=metrics,
            timeout=10,
        )
    assert r["ragas"]["status"] == "ok", r["ragas"]
    for value in r["ragas"]["metrics"].values():
        assert value["value"] == pytest.approx(1)
    assert set(outputs).issubset(set(calls)) and "embedding" in calls
