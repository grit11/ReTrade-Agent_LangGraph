"""从 ReTrade_V2 迁移并重写的 BM25，分词器支持依赖注入。

算法使用正值 IDF 平滑；完整安装时使用 jieba 分词，内置二元分词回退仅用于
在缺少该依赖时维持最小单元测试和模块导入能力。
"""
import math
import re
from collections import Counter
from collections.abc import Callable


def tokenize(text: str) -> list[str]:
    """使用 jieba 将文本切分为 BM25 词项。"""
    text = text.lower()
    try:
        import jieba

        return [t.strip() for t in jieba.lcut(text) if t.strip() and re.search(r"\w", t)]
    except ImportError:
        words = re.findall(r"[a-z0-9]+", text)
        for part in re.findall(r"[\u4e00-\u9fff]+", text):
            words.extend(part[i : i + 2] for i in range(max(1, len(part) - 1)))
        return words


class BM25:
    """轻量 BM25 索引，负责关键词召回与打分。"""

    def __init__(self, texts: list[str], tokenizer: Callable = tokenize, k1=1.5, b=0.75):
        """初始化实例依赖和内部状态。"""
        self.tokenizer = tokenizer
        self.k1 = k1
        self.b = b
        self.docs = [Counter(tokenizer(t)) for t in texts]
        self.lengths = [sum(c.values()) for c in self.docs]
        self.avgdl = sum(self.lengths) / len(texts) if texts else 1
        self.df = Counter(t for c in self.docs for t in c)

    def search(self, query: str, k: int):
        """执行查询并返回匹配结果。"""
        scores = []
        n = len(self.docs)
        query_terms = set(self.tokenizer(query))
        for i, doc in enumerate(self.docs):
            score = 0.0
            for token in query_terms:
                tf = doc.get(token, 0)
                if not tf:
                    continue
                df = self.df[token]
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += (
                    idf
                    * tf
                    * (self.k1 + 1)
                    / (tf + self.k1 * (1 - self.b + self.b * self.lengths[i] / max(self.avgdl, 1)))
                )
            if score > 0:
                scores.append((i, score))
        return sorted(scores, key=lambda pair: (-pair[1], pair[0]))[:k]
