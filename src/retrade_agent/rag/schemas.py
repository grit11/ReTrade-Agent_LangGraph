"""RAG 数据结构模块，定义知识片段和检索结果模型。"""
from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """知识片段模型，保存片段正文、元数据和向量。"""

    chunk_id: str
    document_id: str
    source: str
    text: str
    vector: list[float] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    """检索结果模型，包含命中的片段、分数和来源类型。"""

    contexts: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    scores: list[float] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict)
    evidence_found: bool = False
