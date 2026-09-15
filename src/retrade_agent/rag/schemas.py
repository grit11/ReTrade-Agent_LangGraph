from pydantic import BaseModel, Field
class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    source: str
    text: str
    vector: list[float] = Field(default_factory=list)
class RetrievalResult(BaseModel):
    contexts: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    scores: list[float] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict)
    evidence_found: bool = False
