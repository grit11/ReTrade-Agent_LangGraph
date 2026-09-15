"""倒数排名融合模块，支持列表内去重和稳定的同分排序。"""


def reciprocal_rank_fusion(rankings: list[list[str]], top_k: int, k: int = 60) -> list[tuple[str, float]]:
    """使用倒数排名融合算法合并多路检索结果。"""
    if top_k < 1:
        return []
    if k < 1:
        raise ValueError("k must be positive")
    scores = {}
    for ranking in rankings:
        seen = set()
        for rank, item in enumerate(ranking, 1):
            if not item or item in seen:
                continue
            seen.add(item)
            scores[item] = scores.get(item, 0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:top_k]
