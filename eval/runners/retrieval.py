"""检索关键词代理指标回归脚本，使用临时数据库且不评估答案准确性。"""
import argparse, asyncio, json, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from retrade_agent.config import Settings
from retrade_agent.storage.sqlite import SqliteRepository
from retrade_agent.rag.embeddings import EmbeddingClient
from retrade_agent.rag.vector_local import LocalVectors
from retrade_agent.rag.reranker import SiliconFlowReranker
from retrade_agent.rag.retriever import HybridRetriever
from retrade_agent.services.knowledge import KnowledgeService


async def run(args):
    """执行指定模式的检索评估并写出 JSON 报告。"""
    mode = "live" if args.allow_live else "offline"
    settings = Settings(app_mode=mode, vector_store="local")
    with tempfile.TemporaryDirectory() as temp:
        repo = SqliteRepository(Path(temp) / "eval.sqlite")
        await repo.setup([])
        emb = EmbeddingClient(settings)
        rerank = SiliconFlowReranker(settings)
        try:
            service = KnowledgeService(
                settings, repo, HybridRetriever(settings, emb, LocalVectors(), rerank), emb
            )
            await service.initialize(ROOT / "resources/knowledge")
            data = [
                json.loads(s) for s in (ROOT / "eval/datasets/qa.jsonl").read_text().splitlines() if s.strip()
            ]
            if args.limit:
                data = data[: args.limit]
            rows = []
            for item in data:
                r = await service.search(item["question"])
                known = "知识库中没有" not in item["reference"]
                text = "\n".join(r.contexts)
                hit = any(k in text for k in item["keywords"])
                rows.append(
                    {
                        "id": item["id"],
                        "question": item["question"],
                        "known_answer": known,
                        "keyword_proxy_hit": hit if known else None,
                        "sources": r.sources,
                        "detail": r.detail,
                    }
                )
            applicable = [r for r in rows if r["known_answer"]]
            report = {
                "mode": mode,
                "metric": "keyword_proxy_hit_on_known_answer_items_NOT_answer_accuracy",
                "total": len(rows),
                "applicable": len(applicable),
                "hits": sum(r["keyword_proxy_hit"] for r in applicable),
                "rate": sum(r["keyword_proxy_hit"] for r in applicable) / len(applicable)
                if applicable
                else None,
                "tokenizer": "jieba if installed, otherwise explicit built-in bigrams",
                "rows": rows,
            }
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=2))
            print("Saved:", args.out)
        finally:
            await emb.close()
            await rerank.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--allow-live", action="store_true", help="Authorize paid embedding/rerank requests")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", type=Path, default=ROOT / "eval/reports/retrieval.json")
    asyncio.run(run(p.parse_args()))
