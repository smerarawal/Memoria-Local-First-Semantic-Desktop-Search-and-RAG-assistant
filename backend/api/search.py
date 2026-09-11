"""
API router for semantic search.

Endpoints:
  GET  /search?q=...&top_k=10&extension=.pdf   — semantic file search
  POST /index                                    — trigger processing of pending files
  POST /index/rebuild                            — mark all files as pending + reprocess

GET /search is deliberately a GET (not POST) because:
  - Queries are idempotent and safe (no state change)
  - Results can be cached by the browser
  - The query appears in the URL, making it shareable/bookmarkable
  - Standard convention for search endpoints (Google, Bing, etc.)
"""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query

from db.database import get_db
from schemas.search import IndexTriggerResponse, SearchResponse, SearchResultSchema
from services.document_service import process_pending_files
from services.search_service import search

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResponse)
def semantic_search(
    q: str = Query(..., description="Natural language search query"),
    top_k: int = Query(default=10, ge=1, le=50, description="Max results to return"),
    extension: Optional[str] = Query(
        default=None,
        description="Filter by file extension, e.g. '.pdf'",
    ),
    conn: sqlite3.Connection = Depends(get_db),
):
    """
    Search indexed files by semantic meaning.

    The query is embedded locally using all-MiniLM-L6-v2, then compared
    against all chunk vectors in the FAISS index. Results are aggregated
    per file (best chunk score per file) and returned ranked by relevance.

    Example: GET /search?q=deep+learning+notes&top_k=5&extension=.pdf
    """
    results = search(query=q, top_k=top_k, extension_filter=extension)

    # Deduplicate by file_id (keep highest score per file)
    seen: dict[int, object] = {}
    for r in results:
        if r.file_id not in seen or r.score > seen[r.file_id].score:
            seen[r.file_id] = r
    deduped = sorted(seen.values(), key=lambda r: r.score, reverse=True)[:top_k]

    # Filter out results below a minimum relevance threshold so
    # unrelated files don't pollute results when nothing truly matches.
    MIN_SCORE = 0.10
    deduped = [r for r in deduped if r.score >= MIN_SCORE]

    # Boost results whose filename contains query words — filename is a
    # strong signal that is invisible to pure semantic search.
    query_words = set(q.lower().replace('.', ' ').split())
    for r in deduped:
        stem = r.filename.lower().replace('_', ' ').replace('-', ' ').replace('.', ' ')
        if any(w in stem for w in query_words if len(w) > 1):
            r.score = min(1.0, r.score + 0.30)
            r.relevance_pct = min(100, round(r.score * 100))

    # Re-sort after boost
    deduped.sort(key=lambda r: r.score, reverse=True)

    return SearchResponse(
        query=q,
        total_results=len(deduped),
        results=[
            SearchResultSchema(
                file_id=r.file_id,
                filename=r.filename,
                path=r.path,
                extension=r.extension,
                score=r.score,
                relevance_pct=min(100, round(r.score * 100)),
                top_page=r.top_page,
                top_chunk_text=r.top_chunk_text,
                matched_pages=r.matched_pages,
            )
            for r in deduped
        ],
    )


@router.post("/index", response_model=IndexTriggerResponse)
def trigger_indexing():
    """
    Manually trigger processing of all files currently in status='pending'.
    Useful after adding a large folder to kick off processing immediately
    rather than waiting for the background worker's next poll.
    """
    result = process_pending_files()
    return IndexTriggerResponse(
        **result,
        message=f"Processed {result['processed']} file(s): "
                f"{result['indexed']} indexed, {result['failed']} failed.",
    )


@router.post("/index/rebuild", response_model=IndexTriggerResponse)
def rebuild_index(conn: sqlite3.Connection = Depends(get_db)):
    """
    Reset all indexed/failed files back to 'pending' and reprocess them.
    Use this when you change chunking settings or want to switch embedding
    models (in which case all existing vectors are invalid).
    """
    conn.execute(
        "UPDATE files SET status = 'pending', indexed_at = NULL "
        "WHERE status IN ('indexed', 'failed')"
    )
    conn.commit()

    result = process_pending_files()
    return IndexTriggerResponse(
        **result,
        message=f"Rebuild complete: {result['indexed']} indexed, {result['failed']} failed.",
    )
