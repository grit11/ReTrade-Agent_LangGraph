"""原生 PyMilvus 适配器，不依赖旧版 langchain-milvus。

通过专用集合和活动 generation 隔离本项目数据与过期分块。
"""
import asyncio
import re
from retrade_agent.errors import ConfigurationError


class MilvusVectors:
    """Milvus 向量索引适配器，面向外部向量库读写。"""

    def __init__(self, settings):
        """初始化实例依赖和内部状态。"""
        self.settings = settings
        self.client = None
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", settings.milvus_collection):
            raise ConfigurationError("Milvus collection 名称不合法")

    def _client(self):
        """懒加载并返回 Milvus 客户端实例。"""
        if self.client is None:
            try:
                from pymilvus import MilvusClient
            except ImportError as exc:
                raise ConfigurationError('请安装 pip install -e ".[milvus]"') from exc
            self.client = MilvusClient(
                uri=self.settings.milvus_uri, token=self.settings.milvus_token.get_secret_value(), timeout=10
            )
        return self.client

    async def synchronize(self, chunks, generation):
        """同步知识片段向量到当前向量存储。"""
        if not chunks:
            return

        def write():
            """在线程中写入 Milvus collection，避免阻塞事件循环。"""
            c = self._client()
            name = self.settings.milvus_collection
            dim = len(chunks[0].vector)
            if not c.has_collection(name):
                c.create_collection(
                    collection_name=name,
                    dimension=dim,
                    id_type="string",
                    max_length=128,
                    primary_field_name="id",
                    vector_field_name="vector",
                    auto_id=False,
                    metric_type="COSINE",
                    enable_dynamic_field=True,
                    consistency_level="Strong",
                )
            fields = c.describe_collection(name).get("fields", [])
            for f in fields:
                if f.get("name") == "vector" and int(f.get("params", {}).get("dim", dim)) != dim:
                    raise ConfigurationError("向量维度不一致，请使用新 collection，不要清空旧数据")
            for start in range(0, len(chunks), 128):
                rows = [
                    {"id": x.chunk_id, "vector": x.vector, "generation": generation}
                    for x in chunks[start : start + 128]
                ]
                c.upsert(collection_name=name, data=rows)

        await asyncio.to_thread(write)

    async def search(self, vector, k, generation):
        """在 Milvus 中按向量相似度检索当前 generation 的候选片段。"""
        if not re.fullmatch(r"[a-f0-9]+", generation):
            raise ValueError("invalid generation")

        def search():
            """在 Milvus 中按向量相似度检索当前 generation 的候选片段。"""
            rows = self._client().search(
                collection_name=self.settings.milvus_collection,
                data=[vector],
                limit=k,
                filter=f'generation == "{generation}"',
                output_fields=["id"],
            )
            return [(str(x["id"]), float(x["distance"])) for x in rows[0]] if rows else []

        return await asyncio.to_thread(search)

    async def close(self):
        """释放客户端或缓存持有的资源。"""
        if self.client:
            await asyncio.to_thread(self.client.close)
