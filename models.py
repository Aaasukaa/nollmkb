from pydantic import BaseModel, Field
from config import TOP_K


class QueryRequest(BaseModel):
    text: str
    top_k: int = Field(default=TOP_K, gt=0, le=20)
    dir: str | None = None
    filters: dict | None = None
    min_score: float = 0.0
    rerank: bool = True
    context: bool = False
    bm25: bool = True
    vector: bool = True
