"""Pydantic schemas for search and indexing API endpoints."""

from typing import Optional
from pydantic import BaseModel


class SearchResultSchema(BaseModel):
    file_id: int
    filename: str
    path: str
    extension: str
    score: float
    relevance_pct: int          # score * 100, rounded — for display
    top_page: int
    top_chunk_text: str
    matched_pages: list[int]


class SearchResponse(BaseModel):
    query: str
    total_results: int
    results: list[SearchResultSchema]


class IndexTriggerResponse(BaseModel):
    processed: int
    indexed: int
    failed: int
    message: str
