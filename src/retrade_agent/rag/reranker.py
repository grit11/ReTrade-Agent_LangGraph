"""远程重排模块，不回退到本地 CrossEncoder、torch、transformers 或模型下载。"""
import math
import httpx
from retrade_agent.storage.clients import request_json


class SiliconFlowReranker:
    """SiliconFlow 重排客户端，按查询相关性重新排序候选片段。"""

    def __init__(self, settings, client=None):
        """初始化实例依赖和内部状态。"""
        self.settings = settings
        self.http = client or httpx.AsyncClient(timeout=settings.rerank_timeout)

    async def rerank(self, query, chunks, top_k):
        """调用重排服务对候选片段重新排序。"""
        s = self.settings
        detail = {"provider": "siliconflow", "model": s.rerank_model, "applied": False}
        if not chunks:
            return [], detail
        if not s.rerank_enabled or s.app_mode == "offline":
            return chunks[:top_k], {**detail, "reason": "disabled_or_offline"}
        if not s.rerank_api_key.get_secret_value():
            return chunks[:top_k], {**detail, "reason": "missing_api_key"}
        try:
            data = await request_json(
                self.http,
                s.rerank_base_url.rstrip("/") + "/rerank",
                s.rerank_api_key.get_secret_value(),
                {
                    "model": s.rerank_model,
                    "query": query,
                    "documents": [c.text for c in chunks],
                    "top_n": min(top_k, len(chunks)),
                    "return_documents": False,
                },
            )
            results = data.get("results")
            if not isinstance(results, list) or not results:
                raise ValueError("empty rerank results")
            valid = []
            seen = set()
            for r in results:
                idx = r.get("index")
                score = r.get("relevance_score")
                if type(idx) is not int or idx < 0 or idx >= len(chunks) or idx in seen:
                    raise ValueError("invalid result index")
                if not isinstance(score, (int, float)) or not math.isfinite(score):
                    raise ValueError("invalid score")
                valid.append((idx, float(score)))
                seen.add(idx)
            valid.sort(key=lambda x: -x[1])
            ranked = [chunks[i] for i, _ in valid] + [c for i, c in enumerate(chunks) if i not in seen]
            return ranked[:top_k], {**detail, "applied": True, "scores": [score for _, score in valid]}
        except Exception as exc:
            # Only the exception class is public; never echo upstream response/key.
            return chunks[:top_k], {**detail, "reason": "upstream_failed", "error_type": type(exc).__name__}

    async def close(self):
        """释放客户端或缓存持有的资源。"""
        await self.http.aclose()
