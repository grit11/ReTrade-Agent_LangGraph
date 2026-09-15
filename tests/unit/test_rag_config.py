"""RAG 与配置单元测试，覆盖文档解析、检索排序、HTTP 合同和配置安全。"""

import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path
import pytest
import httpx
from retrade_agent.config import Settings, PROJECT_ROOT
from retrade_agent.errors import AppError, Unavailable
from retrade_agent.rag.loader import parse_document
from retrade_agent.rag.splitter import split_text
from retrade_agent.rag.fusion import reciprocal_rank_fusion
from retrade_agent.rag.bm25 import BM25
from retrade_agent.storage.clients import request_json
from retrade_agent.rag.embeddings import EmbeddingClient
from retrade_agent.rag.vector_local import LocalVectors
from retrade_agent.rag.reranker import SiliconFlowReranker
from retrade_agent.rag.retriever import HybridRetriever
from retrade_agent.services.knowledge import KnowledgeService


@pytest.mark.parametrize("title", ["a.md", "b.txt", "c.markdown"])
def test_text_loaders(title):
    """验证支持的纯文本扩展名均可被解析。"""
    assert "退货" in parse_document(title, "# 退货\n七天内申请。".encode())


def test_invalid_loader():
    """验证不支持的文档类型会被拒绝。"""
    with pytest.raises(AppError):
        parse_document("a.exe", b"foo")


def test_docx_loader():
    """验证 DOCX 文档正文解析。"""
    from docx import Document

    d = Document()
    d.add_paragraph("退款规则")
    b = io.BytesIO()
    d.save(b)
    assert "退款规则" in parse_document("a.docx", b.getvalue())


def test_splitter_stable_and_bounded():
    """验证文本分块稳定、长度受限且参数合法。"""
    text = "# 标题\n" + ("长期测试内容。" * 150)
    c = split_text("test.md", text, 150, 25)
    assert len(c) > 2
    assert c == split_text("test.md", text, 150, 25)
    assert all(len(x.text) <= 150 for x in c)
    assert c[0].chunk_id != split_text("test.md", text + "变更", 150, 25)[0].chunk_id
    with pytest.raises(ValueError):
        split_text("a", "text", 100, 100)


def test_rrf():
    """验证倒数排名融合的顺序、去重和参数检查。"""
    r = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], 3)
    assert r[0][0] == "b" and len(r) == 3
    assert len(reciprocal_rank_fusion([["a", "a"]], 3)) == 1
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([], 3, k=0)


def test_bm25():
    """验证 BM25 相关词召回和无关词空结果。"""
    b = BM25(["退款 退货 七天 规则", "订单 物流 状态"])
    assert b.search("退货", 2)[0][0] == 0
    assert b.search("zzqxyunrelated", 2) == []


def test_preserved_knowledge_source():
    """验证内置知识源文件内容保持预期版本。"""
    data = (PROJECT_ROOT / "resources/knowledge/knowledge_base.md").read_bytes()
    assert (
        hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        == "b5e63dc90222519a1ad54a672322b6c923ef8c6e"
    )


def test_config_original_aliases():
    """验证旧版环境变量别名仍可映射到当前配置。"""
    s = Settings(
        _env_file=None, AIROBOT_LLM_MODEL="original-model", AIROBOT_MILVUS_URI="http://localhost:1953"
    )
    assert s.llm_model == "original-model" and s.milvus_uri.endswith(":1953")
    assert "api_key" not in json.dumps(s.public_info())


def test_config_forbids_destructive_or_insecure_settings():
    """验证配置拒绝破坏性或不安全的启动组合。"""
    with pytest.raises(ValueError):
        Settings(_env_file=None, milvus_reset=True)
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="prod")
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_mode="live", llm_api_key="", embedding_api_key="")


def test_config_secrets_redacted():
    """验证公开信息和对象表示不会泄露密钥。"""
    s = Settings(_env_file=None, llm_api_key="only-test-secret")
    assert "only-test-secret" not in repr(s)
    assert "only-test-secret" not in json.dumps(s.public_info())


async def test_knowledge_dedup_restart_generation(settings, repo):
    """验证知识导入去重、重启重建和 generation 更新。"""
    embed = EmbeddingClient(settings)
    rerank = SiliconFlowReranker(settings)
    try:
        knowledge = KnowledgeService(
            settings, repo, HybridRetriever(settings, embed, LocalVectors(), rerank), embed
        )
        await knowledge.initialize(PROJECT_ROOT / "resources/knowledge")
        before = knowledge.retriever.generation
        r = await knowledge.search("退货规则")
        assert r.evidence_found and r.sources and r.detail["rerank"]["applied"] is False
        p = PROJECT_ROOT / "resources/knowledge/knowledge_base.md"
        duplicate = await knowledge.ingest(p.name, p.read_bytes())
        assert duplicate["deduplicated"]
        assert before == knowledge.retriever.generation
        new = KnowledgeService(
            settings, repo, HybridRetriever(settings, embed, LocalVectors(), rerank), embed
        )
        await new.rebuild()
        assert new.retriever.generation == before
        new.last_error = "remote-failure"
        with pytest.raises(Unavailable):
            await new.search("退货")
        await new.rebuild()
        await new.ingest("new.txt", "配送查询请提供订单号".encode())
        assert new.retriever.generation != before
    finally:
        await embed.close()
        await rerank.close()


async def test_embeddings_http_contract():
    """验证嵌入接口请求字段和响应索引重排。"""
    s = Settings(_env_file=None, app_mode="live", llm_api_key="test", embedding_api_key="test")
    e = EmbeddingClient(s)
    await e.http.aclose()

    def respond(request):
        """返回乱序嵌入结果以验证索引恢复。"""
        data = json.loads(request.content)
        assert data["model"] == s.embedding_model
        assert request.headers["Authorization"] == "Bearer test"
        return httpx.Response(
            200, json={"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]}
        )

    e.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        assert await e.embed(["a", "b"]) == [[1, 0], [0, 1]]
    finally:
        await e.close()


async def test_reranker_index_mapping_and_no_mutation():
    """验证重排索引映射且不修改原始分块。"""
    s = Settings(
        _env_file=None, app_mode="live", llm_api_key="test", embedding_api_key="test", rerank_api_key="test"
    )
    chunks = split_text("test.md", "# 一\n苹果\n# 二\n退款规则")

    def respond(request):
        """返回固定重排结果并检查请求合同。"""
        d = json.loads(request.content)
        assert d["return_documents"] is False and d["top_n"] == 2
        return httpx.Response(
            200,
            json={"results": [{"index": 1, "relevance_score": 0.95}, {"index": 0, "relevance_score": 0.2}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    r = SiliconFlowReranker(s, client)
    try:
        ranked, detail = await r.rerank("退款", chunks, 2)
        assert ranked[0] == chunks[1] and detail["applied"]
        assert chunks[0].text.startswith("# 一")
    finally:
        await r.close()


@pytest.mark.parametrize(
    "results",
    [
        [],
        [{"index": -1, "relevance_score": 0.9}],
        [{"index": 0, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.8}],
    ],
)
async def test_reranker_invalid_falls_back(results):
    """验证无效重排结果会回退到原始顺序。"""
    s = Settings(
        _env_file=None, app_mode="live", llm_api_key="test", embedding_api_key="test", rerank_api_key="test"
    )
    cs = split_text("a.md", "# 一\n退款")
    r = SiliconFlowReranker(
        s,
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"results": results}))
        ),
    )
    try:
        docs, detail = await r.rerank("x", cs, 2)
        assert docs == cs and not detail["applied"]
    finally:
        await r.close()


async def test_http_no_retry_401():
    """验证认证失败响应不会重试。"""
    calls = []

    def respond(req):
        """记录请求并返回固定认证失败响应。"""
        calls.append(1)
        return httpx.Response(401, json={"error": "invalid"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
        with pytest.raises(httpx.HTTPStatusError):
            await request_json(c, "https://example.test/rerank", "test", {}, attempts=3)
    assert len(calls) == 1


async def test_http_retry_503(monkeypatch):
    """验证临时服务错误按配置重试直至成功。"""
    calls = []

    async def no_wait(*a):
        """替换重试等待以缩短单元测试耗时。"""
        pass

    monkeypatch.setattr("retrade_agent.storage.clients.asyncio.sleep", no_wait)

    def respond(req):
        """前两次返回服务错误，第三次返回成功。"""
        calls.append(1)
        return httpx.Response(503 if len(calls) < 3 else 200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
        assert await request_json(c, "https://example.test/rerank", "test", {}, attempts=3) == {"ok": True}
    assert len(calls) == 3


def test_env_import_local_preserves_secrets(tmp_path):
    """验证环境配置迁移保留密钥字面值并阻止覆盖。"""
    spec = importlib.util.spec_from_file_location("import_env", PROJECT_ROOT / "scripts/import_env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = tmp_path / "old.env"
    target = tmp_path / "new.env"
    original.write_text(
        "AIROBOT_LLM_API_KEY='local-test-key$literal'\nAIROBOT_LLM_MODEL=my-model\nAIROBOT_MILVUS_URI=http://localhost:1953\n"
    )
    module.migrate(original, target)
    from dotenv import dotenv_values

    values = dotenv_values(target, interpolate=False)
    assert (
        values["AIROBOT_LLM_API_KEY"] == "local-test-key$literal"
        and values["AIROBOT_LLM_MODEL"] == "my-model"
    )
    assert values["AIROBOT_MILVUS_URI"].endswith(":1953") and values["ASYNC_DATABASE_URL"] == ""
    with pytest.raises(ValueError):
        module.migrate(original, target)


def test_siliconflow_alias_with_blank_primary():
    """验证主重排密钥为空时使用 SiliconFlow 别名。"""
    s = Settings(_env_file=None, AIROBOT_RERANK_API_KEY="", SILICONFLOW_API_KEY="local-test-token")
    assert s.rerank_api_key.get_secret_value() == "local-test-token"


def test_qa_assets_match_source():
    """验证评估问答资产与受控源版本一致。"""
    b = (PROJECT_ROOT / "eval/datasets/qa.jsonl").read_bytes()
    assert (
        hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()
        == "f760b8c8023a31f68dd766a5c37c8c8d528b065d"
    )
