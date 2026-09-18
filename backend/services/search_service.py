"""
Search service — converts a natural language query into ranked file results.

Pipeline:
  Query string
    down embedding_service.embed_one()   -> query vector (384-dim)
    down faiss_index.search(k=80)        -> [(chunk_id, cosine_score)]
    down keyword boost per chunk         -> score += 0.22 per matching query word
    down ChunkRepository.get_many()      -> chunk rows with file_id, page, text
    down FileRepository.get()            -> file metadata (filename, path, ext)
    down aggregate by file               -> max score per file, collect pages
    down rank descending by score        -> final result list

Keyword boosting rationale:
  Semantic embeddings from small models (all-MiniLM-L6-v2) are good at
  conceptual similarity but underweight technical proper nouns like "Shapley",
  "FAISS", "BERT", specific names, acronyms, etc. A literal substring match
  in a chunk is a very strong relevance signal that should dominate over a
  loose semantic match in an unrelated document. We apply a per-term additive
  boost directly to FAISS scores before aggregation.
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


def _keyword_boost(text: str, terms: list[str]) -> float:
    """
    Return an additive score boost based on how many query terms
    appear literally in the chunk text (case-insensitive).

    Each matching term adds 0.22, capped at 0.55 total.
    This ensures a file that literally mentions "shapley" will always
    rank above one that merely talks about related topics.
    """
    if not terms:
        return 0.0
    text_lower = text.lower()
    matches = sum(1 for t in terms if t in text_lower)
    if matches == 0:
        return 0.0
    return min(0.55, 0.22 * matches)


def search(
    query: str,
    top_k: int = 10,
    extension_filter: str | None = None,
) -> list[SearchResult]:
    """
    Semantic search over the indexed corpus, with keyword match boosting.

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

    # Precompute query terms for keyword boosting (skip very short words)
    query_terms = [w.lower() for w in query.strip().split() if len(w) > 2]

    # 2. Retrieve top candidates from FAISS — fetch more (x8) so keyword
    #    boosting has enough candidates across all files to work with.
    raw_results = faiss_index.search(query_vector, k=min(top_k * 8, 80))

    if not raw_results:
        return []

    chunk_ids = [cid for cid, _ in raw_results]
    score_map = {cid: score for cid, score in raw_results}

    # 3. Fetch chunk + file metadata from SQLite
    with db_session() as conn:
        chunk_repo = ChunkRepository(conn)
        file_repo = FileRepository(conn)

        chunks = chunk_repo.get_many(chunk_ids)

        # 3a. Apply keyword boost to each chunk score immediately
        boosted_score_map: dict[int, float] = {}
        for chunk in chunks:
            base = score_map.get(chunk["chunk_id"], 0.0)
            boost = _keyword_boost(chunk["text"], query_terms)
            boosted_score_map[chunk["chunk_id"]] = base + boost
            if boost > 0:
                logger.debug(
                    "[search] keyword boost +%.2f on chunk %d (%s)",
                    boost, chunk["chunk_id"], chunk["text"][:60]
                )

        # Group by file_id
        file_chunks: dict[int, list] = {}
        for chunk in chunks:
            fid = chunk["file_id"]
            if fid not in file_chunks:
                file_chunks[fid] = []
            file_chunks[fid].append(chunk)

        # 4. Aggregate per file — pick best chunk by BOOSTED score
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

            best_chunk = max(
                file_chunk_list,
                key=lambda c: boosted_score_map.get(c["chunk_id"], 0.0)
            )
            best_score = boosted_score_map.get(best_chunk["chunk_id"], 0.0)
            matched_pages = sorted({c["page_number"] for c in file_chunk_list})

            results.append(SearchResult(
                file_id=fid,
                filename=file_row["filename"],
                path=file_row["path"],
                extension=file_row["extension"],
                score=round(best_score, 4),
                top_page=best_chunk["page_number"],
                top_chunk_text=best_chunk["text"][:300],
                matched_pages=matched_pages,
            ))

    # 5. Sort by boosted score descending, take top_k
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
