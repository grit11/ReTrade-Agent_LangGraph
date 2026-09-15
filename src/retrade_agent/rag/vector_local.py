"""本地向量库模块，在内存中保存向量并提供余弦相似度检索。"""
import math


class LocalVectors:
    """Vectors persist in document registry; no local neural model is loaded."""

    def __init__(self):
        """初始化实例依赖和内部状态。"""
        self.items = []

    async def synchronize(self, chunks, generation):
        """同步知识片段向量到当前向量存储。"""
        self.items = list(chunks)

    async def search(self, vector, k, generation):
        """在本地向量列表中按余弦相似度检索候选片段。"""

        def cosine(v):
            """计算查询向量与本地向量之间的余弦相似度。"""
            if len(vector) != len(v):
                return -1.0
            norm = math.sqrt(sum(x * x for x in vector) * sum(x * x for x in v))
            return sum(a * b for a, b in zip(vector, v)) / norm if norm else 0

        rows = [(c.chunk_id, cosine(c.vector)) for c in self.items]
        return sorted(rows, key=lambda x: (-x[1], x[0]))[:k]

    async def close(self):
        """释放客户端或缓存持有的资源。"""
        pass
