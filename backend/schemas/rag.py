"""
Pydantic schemas for the RAG (Retrieval-Augmented Generation) endpoint.

RAGRequest  — incoming POST body (query + optional top_k)
RAGSource   — a single retrieved source document used as context
RAGResponse — the full response: answer text + source list + metadata
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class RAGRequest(BaseModel):
    query: str = Field(..., description="Natural language question to answer")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of chunks to retrieve")
    api_key: Optional[str] = Field(default=None, description="Optional Google Gemini API key")


class RAGSource(BaseModel):
    filename: str
    path: str
    snippet: str   # The chunk text used as context
    score: float   # Cosine similarity score from FAISS


class RAGResponse(BaseModel):
    query: str
    answer: str
    sources: List[RAGSource]
    model: str     # Which LLM model was used (or "none" on error)
