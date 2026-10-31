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
import re
from dataclasses import dataclass

from db.database import db_session
from db.repositories import ChunkRepository, FileRepository
from services.embedding_service import embedding_service
from vector.faiss_index import faiss_index
from services.query_intent import parse_query_intent, score_file_candidate

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
    appear literally as distinct words in the chunk text (case-insensitive).

    Each matching term adds 0.22, capped at 0.55 total.
    This ensures a file that literally mentions "shapley" will always
    rank above one that merely talks about related topics.
    """
    if not terms:
        return 0.0
    text_lower = text.lower()
    matches = sum(1 for t in terms if re.search(r"\b" + re.escape(t) + r"\b", text_lower))
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

    # Precompute query terms for keyword boosting (skip very short words and meta query words)
    stop_meta = {
        "what", "does", "about", "show", "tell", "explain", "notes", "file", "files",
        "document", "paper", "say", "where", "which", "did", "the", "and", "for", "with",
        "you", "your", "mine", "this", "that", "these", "those", "have", "had", "doing",
        "how", "when", "why", "who", "can", "could", "would", "should", "some", "image",
        "picture", "photo", "pic", "photos", "pictures", "images", "find"
    }
    query_terms = [
        re.sub(r"[^\w]", "", w.lower())
        for w in query.strip().split()
        if len(re.sub(r"[^\w]", "", w)) > 2 and re.sub(r"[^\w]", "", w.lower()) not in stop_meta
    ]
    if not query_terms:
        query_terms = [re.sub(r"[^\w]", "", w.lower()) for w in query.strip().split() if len(re.sub(r"[^\w]", "", w)) > 2]

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

        # Include direct filename matches from DB so files named e.g. "dog.jpg" or "dog_park.png"
        # are guaranteed to be evaluated even in large corpora
        cursor = conn.cursor()
        for term in query_terms:
            if len(term) >= 3:
                cursor.execute(
                    """
                    SELECT c.chunk_id, f.filename
                    FROM chunks c
                    JOIN files f ON c.file_id = f.file_id
                    WHERE f.status = 'indexed' AND LOWER(f.filename) LIKE ?
                    LIMIT 20
                    """,
                    (f"%{term}%",)
                )
                for row in cursor.fetchall():
                    cid, fn = row[0], row[1]
                    fn_words = set(re.findall(r"[a-z0-9]+", fn.lower()))
                    if any(w == term for w in fn_words):
                        if cid not in score_map:
                            score_map[cid] = 0.50
                            chunk_ids.append(cid)

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

            # Boost if query terms appear directly in the filename
            fn_lower = file_row["filename"].lower()
            fn_words = set(re.findall(r"[a-z0-9]+", fn_lower))
            fn_matches = sum(1 for t in query_terms if any(w == t for w in fn_words))
            if fn_matches > 0:
                best_score += min(0.40, 0.20 * fn_matches)

            # New: small extra boost for plain‑text files (if you still want it)
            # if file_row["extension"] == ".txt":
            #    best_score += 0.25

            # No blanket image boost — images rank purely by semantic similarity
            # plus keyword/filename boosts already applied above.

            # Prioritize user's own files over third-party files
            if 'smera' in fn_lower:
                best_score += 0.15
            for tp in ('yuvraj', 'debnath', 'ayush'):
                if tp in fn_lower and not any(tp in t for t in query_terms):
                    best_score -= 0.35

            matched_pages = sorted({c["page_number"] for c in file_chunk_list})

            raw_snippet = best_chunk["text"]
            if raw_snippet.startswith("IMAGE_DESCRIPTION:"):
                raw_snippet = raw_snippet.replace("IMAGE_DESCRIPTION: ", "", 1).strip()

            results.append(SearchResult(
                file_id=fid,
                filename=file_row["filename"],
                path=file_row["path"],
                extension=file_row["extension"],
                score=round(min(best_score, 1.0), 4),
                top_page=best_chunk["page_number"],
                top_chunk_text=raw_snippet[:300],
                matched_pages=matched_pages,
            ))

    # 5. Sort by boosted score descending, take top_k
    results.sort(key=lambda r: r.score, reverse=True)
    base_results = results[:top_k]

    # 6. Intent-aware reranking for version/temporal queries
    #    Applies the same scoring engine used by RAG to "Find by meaning" tab
    q_info = parse_query_intent(query)
    is_intent_query = (
        q_info["wants_older"]
        or q_info["wants_newer"]
        or q_info["q_number"] is not None
        or bool(q_info["anchor_terms"])
    )
    subj_tokens = q_info["subj_tokens"]

    if not is_intent_query or not subj_tokens:
        return base_results

    logger.info(
        "[search] Intent query detected: wants_older=%s wants_newer=%s q_number=%s anchor=%s subj=%s",
        q_info["wants_older"], q_info["wants_newer"], q_info["q_number"],
        q_info["anchor_terms"], subj_tokens,
    )

    # Collect candidate files by filename match on subject tokens
    with db_session() as conn:
        cursor = conn.cursor()
        candidates: dict[int, dict] = {}

        for tok in subj_tokens:
            cursor.execute(
                "SELECT file_id, filename, path, extension, modified_at "
                "FROM files WHERE LOWER(filename) LIKE ? AND status = 'indexed'",
                (f"%{tok}%",),
            )
            for row in cursor.fetchall():
                candidates[row["file_id"]] = row

        # Also include any files returned by the base semantic search
        for r in base_results:
            if r.file_id not in candidates:
                cursor.execute(
                    "SELECT file_id, filename, path, extension, modified_at "
                    "FROM files WHERE file_id = ? AND status = 'indexed'",
                    (r.file_id,),
                )
                row = cursor.fetchone()
                if row:
                    candidates[r.file_id] = row

        # Score all candidates using intent scoring
        scored_files: list[tuple[float, SearchResult]] = []
        for fid, frow in candidates.items():
            cursor.execute(
                "SELECT chunk_id, page_number, text FROM chunks "
                "WHERE file_id = ? ORDER BY page_number ASC, chunk_id ASC LIMIT 6",
                (fid,),
            )
            chunks = cursor.fetchall()
            chunk_texts = [c["text"] for c in chunks]

            cand_score = score_file_candidate(
                frow["filename"], frow["modified_at"], q_info, chunk_texts,
            )

            # Find the best snippet — prefer one containing anchor terms
            snippet = chunks[0]["text"] if chunks else ""
            top_page = chunks[0]["page_number"] if chunks else 1
            if q_info["anchor_terms"]:
                for c in chunks:
                    if any(t in c["text"].lower() for t in q_info["anchor_terms"]):
                        snippet = c["text"]
                        top_page = c["page_number"]
                        break

            # Normalize the raw intent score (typically -1000..+700) to 0..1
            if cand_score > 0:
                display_score = min(1.0, 0.70 + (cand_score / 2000.0))
            else:
                display_score = max(0.0, 0.50 + (cand_score / 2000.0))

            raw_snippet = snippet[:300]
            if raw_snippet.startswith("IMAGE_DESCRIPTION:"):
                raw_snippet = raw_snippet.replace("IMAGE_DESCRIPTION: ", "", 1).strip()

            scored_files.append((
                cand_score,
                SearchResult(
                    file_id=fid,
                    filename=frow["filename"],
                    path=frow["path"],
                    extension=frow["extension"],
                    score=round(display_score, 4),
                    top_page=top_page,
                    top_chunk_text=raw_snippet,
                    matched_pages=[top_page],
                ),
            ))

    # Filter out heavily penalized files, sort by intent score
    scored_files = [x for x in scored_files if x[0] > -500.0]
    scored_files.sort(key=lambda x: (x[0], x[1].score), reverse=True)
    intent_results = [x[1] for x in scored_files[:top_k]]

    if intent_results:
        logger.info(
            "[search] Intent reranking: top result = %s (score=%.4f)",
            intent_results[0].filename, intent_results[0].score,
        )
        return intent_results

    return base_results
