"""
Search service — converts a natural language query into ranked file results.

Pipeline:
  Query string
    ↓ embedding_service.embed_one()   → query vector (384-dim)
    ↓ faiss_index.search(k=20)        → [(chunk_id, cosine_score)]
    ↓ ChunkRepository.get_many()      → chunk rows with file_id, page, text
    ↓ FileRepository.get()            → file metadata (filename, path, ext)
    ↓ aggregate by file               → max score per file, collect pages
    ↓ rank descending by score        → final result list

Aggregation rationale:
  A PDF has 200 chunks. 15 of them match the query. Showing 15 separate
  results all from the same file is noisy and unhelpful. We take the best
  score across all matching chunks and surface the file once, with the top
  matching page number shown as the citation. This matches what real
  search products do — show the document, not the fragment.

  The top_chunk_text is kept in the result so the UI can show a snippet
  of the most relevant passage — like Google's "featured snippet" idea.
"""

import logging
from dataclasses import dataclass

from db.database import db_session
from db.repositories import ChunkRepository, FileRepository
from services.embedding_service import embedding_service
from vector.faiss_index import faiss_index

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    file_id: int
    filename: str
    path: str
    extension: str
    score: float          # Best cosine similarity across all matching chunks
    top_page: int         # Page of the best-matching chunk (for citation)
    top_chunk_text: str   # Text of the best-matching chunk (for snippet)
    matched_pages: list[int]  # All pages that had matching chunks


def search(
    query: str,
    top_k: int = 10,
    extension_filter: str | None = None,
) -> list[SearchResult]:
    """
    Semantic search over the indexed corpus.

    Args:
        query:            Natural language query string.
        top_k:            Max number of *files* to return (not chunks).
        extension_filter: Optional extension like ".pdf" to restrict results.

    Returns:
        List of SearchResult, sorted descending by score. Empty if no indexed
        files or if the query can't be embedded.
    """
    if not query.strip():
        return []

    if faiss_index.ntotal == 0:
        logger.info("[search] FAISS index is empty — nothing to search")
        return []

    # 1. Embed query
    query_vector = embedding_service.embed_one(query.strip())

    # 2. Retrieve top candidates from FAISS
    #    We ask for more chunks than files we want (×5) because multiple
    #    chunks may come from the same file and we aggregate them.
    raw_results = faiss_index.search(query_vector, k=min(top_k * 5, 50))

    if not raw_results:
        return []

    chunk_ids = [cid for cid, _ in raw_results]
    score_map = {cid: score for cid, score in raw_results}

    # 3. Fetch chunk + file metadata from SQLite
    with db_session() as conn:
        chunk_repo = ChunkRepository(conn)
        file_repo = FileRepository(conn)

        chunks = chunk_repo.get_many(chunk_ids)

        # Group by file_id
        file_chunks: dict[int, list] = {}
        for chunk in chunks:
            fid = chunk["file_id"]
            if fid not in file_chunks:
                file_chunks[fid] = []
            file_chunks[fid].append(chunk)

        # 4. Aggregate per file
        results: list[SearchResult] = []
        for fid, file_chunk_list in file_chunks.items():
            file_row = file_repo.get(fid)
            if file_row is None:
                continue
            if file_row["status"] == "deleted":
                continue

            # Apply extension filter
            if extension_filter and file_row["extension"] != extension_filter:
                continue

            # Find best chunk by score
            best_chunk = max(
                file_chunk_list,
                key=lambda c: score_map.get(c["chunk_id"], 0.0)
            )
            best_score = score_map.get(best_chunk["chunk_id"], 0.0)
            matched_pages = sorted({c["page_number"] for c in file_chunk_list})

            results.append(SearchResult(
                file_id=fid,
                filename=file_row["filename"],
                path=file_row["path"],
                extension=file_row["extension"],
                score=round(best_score, 4),
                top_page=best_chunk["page_number"],
                top_chunk_text=best_chunk["text"][:300],  # Snippet for UI
                matched_pages=matched_pages,
            ))

    # 5. Sort by score descending, take top_k
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
