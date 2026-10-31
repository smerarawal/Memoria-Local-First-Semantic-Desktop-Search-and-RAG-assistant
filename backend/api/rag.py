"""
RAG (Retrieval-Augmented Generation) endpoint powered by Google Gemini API.

POST /rag
  - Fast semantic + keyword retrieval of target chunks
  - Direct, focused prompt to Google Gemini API
  - Returns grounded answer with citations and timing metrics

POST /rag/stream
  - Server-Sent Events (SSE) streaming for real-time progressive response
"""

import json
import logging
import os
import queue
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from db.database import db_session
from schemas.rag import RAGRequest, RAGResponse, RAGSource
from services.query_intent import (
    OLDER_SIGNALS as _OLDER_SIGNALS,
    NEWER_SIGNALS as _NEWER_SIGNALS,
    VERSION_KEYWORDS as _VERSION_KEYWORDS,
    STOP_WORDS as _STOP_WORDS,
    extract_file_version_number as _extract_file_version_number,
    extract_query_version_number as _extract_query_version_number,
    parse_query_intent as _parse_query_intent,
    score_file_candidate as _score_file_candidate,
)
from services.search_service import search

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])

# Active, low-latency models supported in the Google GenAI SDK (tested for fastest TTFT)
CANDIDATE_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite",
]

# ---------------------------------------------------------------------------
# Response-level LRU cache — avoids re-calling Gemini for identical queries
# ---------------------------------------------------------------------------
_rag_cache: OrderedDict = OrderedDict()
_RAG_CACHE_MAX = 64


def _cache_key(query: str, top_k: int) -> str:
    return f"{query.strip().lower()}|{top_k}"



# ---------------------------------------------------------------------------
# Version/temporal awareness — imported from services.query_intent
# (constants and functions are aliased at module top via the import block)
# ---------------------------------------------------------------------------


def _version_score(filename: str, query_lower: str) -> float:
    """Legacy helper kept for backwards compatibility."""
    q_info = _parse_query_intent(query_lower)
    return _score_file_candidate(filename, None, q_info, [])


def _get_candidate_keys(user_key: Optional[str] = None) -> list[str]:
    """
    Collect all available Gemini API keys in priority order:
    1. Direct key from frontend request
    2. OS Environment variable GEMINI_API_KEY
    3. backend/.env, project root .env, frontend/.env
    """
    keys = []
    if user_key and user_key.strip():
        keys.append(user_key.strip())

    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key and env_key.strip() and env_key.strip() not in keys:
        keys.append(env_key.strip())

    candidate_paths = [
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / "frontend" / ".env",
    ]
    for cp in candidate_paths:
        if cp.exists():
            try:
                for line in cp.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k in ("GEMINI_API_KEY", "VITE_GEMINI_API_KEY") and v and v not in keys:
                            keys.append(v)
            except Exception:
                pass
    return keys


def _get_groq_key(user_key: Optional[str] = None) -> Optional[str]:
    """
    Collect Groq API key:
    1. Direct key from frontend request
    2. OS Environment variable GROQ_API_KEY
    3. backend/.env, project root .env, frontend/.env
    """
    if user_key and user_key.strip():
        return user_key.strip()

    env_key = os.environ.get("GROQ_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    candidate_paths = [
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / "frontend" / ".env",
    ]
    for cp in candidate_paths:
        if cp.exists():
            try:
                for line in cp.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k in ("GROQ_API_KEY", "VITE_GROQ_API_KEY") and v:
                            return v
            except Exception:
                pass
    return None



def _extract_topic_terms(query: str) -> list[str]:
    """
    Extract meaningful topic words and their common word stems (e.g. internships -> internship).
    """
    stop_words = {
        "what", "does", "about", "show", "tell", "explain", "notes", "file", "files",
        "document", "paper", "say", "where", "which", "did", "the", "and", "for", "with",
        "you", "your", "mine", "this", "that", "these", "those", "have", "had", "doing",
        "how", "when", "why", "who", "can", "could", "would", "should", "some",
    }
    words = [re.sub(r"[^\w]", "", w.lower()) for w in query.split()]
    raw_terms = [w for w in words if len(w) > 2 and w not in stop_words]
    stems = set(raw_terms)
    for w in raw_terms:
        for suffix in ("ships", "ship", "ing", "ies", "es", "ed", "s"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                stems.add(w[:-len(suffix)])
    return list(stems)


def _retrieve_context(query: str, top_k: int = 5):
    """
    Retrieve top candidate chunks for the query using semantic search + keyword filtering.
    Also does direct DB filename lookup when the query contains filename fragments or folder names.
    """
    t0 = time.perf_counter()
    query_lower = query.lower()

    # --- Direct filename & version-aware search in DB ---
    target_result = None
    query_info = _parse_query_intent(query)
    subj_tokens = query_info["subj_tokens"]

    if subj_tokens:
        with db_session() as conn:
            cursor = conn.cursor()
            candidates: dict[int, dict] = {}
            for token in subj_tokens:
                cursor.execute(
                    "SELECT file_id, filename, path, extension, modified_at FROM files WHERE LOWER(filename) LIKE ? AND status != 'deleted' LIMIT 100",
                    (f"%{token}%",)
                )
                for row in cursor.fetchall():
                    candidates[row["file_id"]] = row

            if candidates:
                scored_candidates = []
                for fid, row in candidates.items():
                    cursor.execute(
                        "SELECT text FROM chunks WHERE file_id = ? ORDER BY page_number ASC, chunk_id ASC LIMIT 5",
                        (fid,)
                    )
                    chunk_texts = [cr["text"] for cr in cursor.fetchall()]
                    cand_score = _score_file_candidate(
                        row["filename"],
                        row["modified_at"],
                        query_info,
                        chunk_texts
                    )
                    scored_candidates.append((cand_score, row))

                scored_candidates.sort(key=lambda x: (x[0], -len(x[1]["filename"])), reverse=True)
                best_score, best_row = scored_candidates[0]

                if best_score > 0:
                    from services.search_service import SearchResult
                    cursor.execute(
                        "SELECT chunk_id, page_number, text FROM chunks WHERE file_id = ? ORDER BY chunk_id ASC LIMIT 1",
                        (best_row["file_id"],)
                    )
                    top_chunk_row = cursor.fetchone()
                    if top_chunk_row:
                        target_result = SearchResult(
                            file_id=best_row["file_id"],
                            filename=best_row["filename"],
                            path=best_row["path"],
                            extension=best_row["extension"],
                            score=1.0,
                            top_page=top_chunk_row["page_number"],
                            top_chunk_text=top_chunk_row["text"][:300],
                            matched_pages=[top_chunk_row["page_number"]],
                        )
                        logger.info(
                            "[rag] Direct filename/version match -> %s (score=%.1f, subj_tokens=%s)",
                            best_row["filename"],
                            best_score,
                            subj_tokens
                        )

    # --- Standard semantic search ---
    raw_results = search(query=query, top_k=top_k)

    if not raw_results and target_result is None:
        return [], [], round((time.perf_counter() - t0) * 1000, 1), None

    # If no direct filename match, pick best semantic result, preferring name matches
    if target_result is None:
        target_result = raw_results[0]
        for r in raw_results:
            clean_name = re.sub(r"[\._\-]", " ", r.filename.lower())
            name_words = [w for w in clean_name.split() if len(w) >= 3]
            if any(w in query_lower for w in name_words):
                target_result = r
                break

    topic_terms = _extract_topic_terms(query)
    chunks_to_use = []

    with db_session() as conn:
        cursor = conn.cursor()
        if topic_terms:
            like_conditions = " OR ".join(["LOWER(text) LIKE ?" for _ in topic_terms])
            params = [target_result.file_id] + [f"%{t}%" for t in topic_terms]
            query_sql = f"""
                SELECT chunk_id, page_number, text
                FROM chunks
                WHERE file_id = ? AND ({like_conditions})
                ORDER BY page_number ASC, chunk_id ASC
                LIMIT 8
            """
            cursor.execute(query_sql, params)
            for row in cursor.fetchall():
                chunks_to_use.append({
                    "filename": target_result.filename,
                    "path": target_result.path,
                    "page_number": row["page_number"],
                    "text": row["text"],
                    "score": target_result.score,
                    "file_id": target_result.file_id,
                    "extension": target_result.extension,
                })

        # Fallback: grab all chunks from the target file (good for images with OCR text)
        if not chunks_to_use:
            cursor.execute(
                "SELECT chunk_id, page_number, text FROM chunks WHERE file_id = ? ORDER BY page_number ASC, chunk_id ASC LIMIT 8",
                (target_result.file_id,)
            )
            for row in cursor.fetchall():
                chunks_to_use.append({
                    "filename": target_result.filename,
                    "path": target_result.path,
                    "page_number": row["page_number"],
                    "text": row["text"],
                    "score": target_result.score,
                    "file_id": target_result.file_id,
                    "extension": target_result.extension,
                })

        # If still empty, fall back to top semantic results
        if not chunks_to_use and raw_results:
            for r in raw_results[:8]:
                chunks_to_use.append({
                    "filename": r.filename,
                    "path": r.path,
                    "page_number": r.top_page,
                    "text": r.top_chunk_text,
                    "score": r.score,
                    "file_id": r.file_id,
                    "extension": r.extension,
                })

    sources = [
        RAGSource(
            filename=c["filename"],
            path=c["path"],
            snippet=c["text"][:300],
            score=c["score"],
            file_id=c.get("file_id"),
            extension=c.get("extension"),
        )
        for c in chunks_to_use[:8]
    ]
    search_ms = round((time.perf_counter() - t0) * 1000, 1)
    return chunks_to_use, sources, search_ms, target_result



def _build_prompt(query: str, chunks: list[dict]) -> str:
    # Use up to 8 excerpts with expanded snippet size for deeper context
    context_blocks = []
    for i, c in enumerate(chunks[:8], start=1):
        snippet_text = c['text'].strip()[:1500]
        context_blocks.append(f"[{i}] {c['filename']} (Page {c['page_number']}):\n{snippet_text}")
    context_str = "\n\n".join(context_blocks)

    return (
        "You are an expert AI research and document assistant in Memoria.\n"
        "Provide a comprehensive, in-depth, and well-structured answer to the user's question based strictly on the provided document excerpts.\n\n"
        "Guidelines for your response:\n"
        "- Do not provide short, superficial, or one-sentence summaries. Dig thoroughly into the specifics, facts, numbers, dates, comparisons, context, and findings contained in the source documents.\n"
        "- Explain the underlying concepts, methodology, background, and nuances clearly.\n"
        "- Synthesize information across multiple excerpts when relevant.\n"
        "- Format cleanly with Markdown:\n"
        "  ### Overview\n"
        "  A substantive summary directly answering the question with core conclusions.\n\n"
        "  ### Detailed Analysis & Findings\n"
        "  Exhaustive explanations and bullet points covering all facts, data points, metrics, and technical context from the excerpts.\n\n"
        "  ### Additional Context & Nuance\n"
        "  Any relevant background, implications, limitations, or related topics mentioned in the excerpts.\n\n"
        "  ### Citations\n"
        "  Explicitly cite the source filenames and page numbers for each fact or claim, e.g. (*Document.pdf*, p. X).\n\n"
        f"Document Excerpts:\n{context_str}\n\n"
        f"Question: {query}\n\n"
        "Detailed Answer:"
    )


def _call_gemini(prompt: str, candidate_keys: list[str]) -> tuple[str, str, float]:
    """
    Query Google Gemini API, trying available keys and models in order.
    Returns (answer_text, model_name, elapsed_ms).
    """
    from google import genai
    from google.genai import types

    gen_config = types.GenerateContentConfig(
        max_output_tokens=2048,
        temperature=0.2,
    )

    t0 = time.perf_counter()
    last_error = None
    for api_key in candidate_keys:
        if not api_key:
            continue
        try:
            client = genai.Client(api_key=api_key.strip())
            for model_name in CANDIDATE_MODELS:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=gen_config,
                    )
                    if response.text and response.text.strip():
                        llm_ms = round((time.perf_counter() - t0) * 1000, 1)
                        return response.text.strip(), model_name, llm_ms
                except Exception as model_err:
                    last_error = model_err
                    err_str = str(model_err)
                    logger.info("[rag] Model %s failed: %s", model_name, model_err)
                    if "API_KEY_INVALID" in err_str or "API key not valid" in err_str:
                        break
                    continue
        except Exception as client_err:
            last_error = client_err
            continue

    raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")


def _call_gemini_stream(prompt: str, candidate_keys: list[str]):
    """
    Stream tokens from Google Gemini API.
    Yields (token_text, model_name).
    """
    from google import genai
    from google.genai import types

    gen_config = types.GenerateContentConfig(
        max_output_tokens=2048,
        temperature=0.2,
    )

    last_error = None
    for api_key in candidate_keys:
        if not api_key:
            continue
        try:
            client = genai.Client(api_key=api_key.strip())
            for model_name in CANDIDATE_MODELS:
                try:
                    stream = client.models.generate_content_stream(
                        model=model_name,
                        contents=prompt,
                        config=gen_config,
                    )
                    yielded = False
                    for chunk in stream:
                        if chunk.text:
                            yielded = True
                            yield chunk.text, model_name
                    if yielded:
                        return
                except Exception as model_err:
                    last_error = model_err
                    err_str = str(model_err)
                    logger.info("[rag-stream] Model %s failed: %s", model_name, model_err)
                    if "API_KEY_INVALID" in err_str or "API key not valid" in err_str:
                        break
                    continue
        except Exception as client_err:
            last_error = client_err
            continue

    raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")


def _call_groq(prompt: str, groq_key: str) -> tuple[str, str, float]:
    """
    Query Groq API with OpenAI client.
    Returns (answer_text, model_name, elapsed_ms).
    """
    from openai import OpenAI

    t0 = time.perf_counter()
    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=groq_key,
        timeout=15.0,
    )

    models_to_try = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    ]

    last_error = None
    for model_name in models_to_try:
        try:
            resp = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are Memoria, an expert AI document assistant. Provide comprehensive, deeply detailed, and structured answers based strictly on document excerpts."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                temperature=0.2,
            )
            content = resp.choices[0].message.content or ""
            if content.strip():
                elapsed = round((time.perf_counter() - t0) * 1000, 1)
                return content.strip(), f"groq/{model_name}", elapsed
        except Exception as exc:
            last_error = exc
            logger.warning("[rag-groq] Model %s failed: %s", model_name, exc)
            continue

    raise RuntimeError(f"All Groq models failed. Last error: {last_error}")


def _call_groq_stream(prompt: str, groq_key: str):
    """
    Stream tokens from Groq API via the openai client.
    Yields (token_text, model_name).
    """
    from openai import OpenAI

    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=groq_key,
        timeout=15.0,
    )

    models_to_try = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    ]

    last_error = None
    for model_name in models_to_try:
        try:
            stream = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are Memoria, an expert AI document assistant. Provide comprehensive, deeply detailed, and structured answers based strictly on document excerpts."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                temperature=0.2,
                stream=True,
            )
            yielded = False
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yielded = True
                    yield chunk.choices[0].delta.content, f"groq/{model_name}"
            if yielded:
                return
        except Exception as exc:
            last_error = exc
            logger.warning("[rag-groq-stream] Model %s failed: %s", model_name, exc)
            continue

    raise RuntimeError(f"All Groq models failed. Last error: {last_error}")


@router.post("/rag", response_model=RAGResponse)
def rag_query(body: RAGRequest):
    """
    Answer a natural language question using document chunks + AI (Groq or Gemini).
    Cached: identical queries within the session return instantly.
    """
    t_start = time.perf_counter()

    # --- Check response cache first ---
    ck = _cache_key(body.query, body.top_k)
    if ck in _rag_cache:
        _rag_cache.move_to_end(ck)
        cached_resp = _rag_cache[ck]
        cache_ms = round((time.perf_counter() - t_start) * 1000, 1)
        logger.info("[rag] Cache HIT for: %.60s (%.1fms)", body.query, cache_ms)
        return RAGResponse(
            query=body.query,
            answer=cached_resp["answer"],
            sources=cached_resp["sources"],
            model=cached_resp["model"],
            metrics={"search_ms": 0, "llm_ms": 0, "total_ms": cache_ms, "cached": True},
        )

    chunks_to_use, sources, search_ms, target_result = _retrieve_context(body.query, body.top_k)

    if not chunks_to_use or target_result is None:
        return RAGResponse(
            query=body.query,
            answer="No relevant documents found in the index. Make sure your folders are added and indexed in Setup before asking questions.",
            sources=[],
            model="none",
            metrics={"search_ms": search_ms, "llm_ms": 0, "total_ms": search_ms},
        )

    pref_provider = (body.provider or "auto").lower()
    groq_key = _get_groq_key(body.groq_api_key)
    candidate_gemini_keys = _get_candidate_keys(body.api_key)

    if not groq_key and not candidate_gemini_keys:
        top_snippet = chunks_to_use[0]["text"] if chunks_to_use else target_result.top_chunk_text
        return RAGResponse(
            query=body.query,
            answer=(
                f"**API Key Required**: Please configure a Groq or Gemini API key in Setup.\n\n"
                f"**Direct excerpt from `{target_result.filename}`:**\n> {top_snippet.strip()}"
            ),
            sources=sources,
            model="direct-extract-fallback",
            metrics={"search_ms": search_ms, "llm_ms": 0, "total_ms": search_ms},
        )

    prompt = _build_prompt(body.query, chunks_to_use)

    try:
        answer = None
        model_used = None
        llm_ms = 0.0

        if pref_provider in ("auto", "groq") and groq_key:
            try:
                answer, model_used, llm_ms = _call_groq(prompt, groq_key)
            except Exception as e:
                logger.warning("[rag] Groq failed, falling back to Gemini: %s", e)
                if pref_provider == "groq":
                    raise e

        if not answer and candidate_gemini_keys:
            answer, model_used, llm_ms = _call_gemini(prompt, candidate_gemini_keys)

        if not answer:
            raise RuntimeError("No AI response generated.")

        total_ms = round((time.perf_counter() - t_start) * 1000, 1)

        # Cache the successful response
        _rag_cache[ck] = {"answer": answer, "sources": sources, "model": model_used}
        if len(_rag_cache) > _RAG_CACHE_MAX:
            _rag_cache.popitem(last=False)
        logger.info("[rag] Cache MISS, stored: %.60s (%.1fs)", body.query, total_ms / 1000)

        return RAGResponse(
            query=body.query,
            answer=answer,
            sources=sources,
            model=model_used,
            metrics={"search_ms": search_ms, "llm_ms": llm_ms, "total_ms": total_ms},
        )
    except Exception as exc:
        logger.error("[rag] AI Error: %s", exc)
        top_snippet = chunks_to_use[0]["text"] if chunks_to_use else target_result.top_chunk_text
        total_ms = round((time.perf_counter() - t_start) * 1000, 1)
        return RAGResponse(
            query=body.query,
            answer=(
                f"**API Error**: {exc}\n\n"
                f"**Direct excerpt from `{target_result.filename}`:**\n> {top_snippet.strip()}"
            ),
            sources=sources,
            model="direct-extract-fallback",
            metrics={"search_ms": search_ms, "llm_ms": 0, "total_ms": total_ms},
        )


@router.post("/rag/stream")
def rag_query_stream(body: RAGRequest):
    """
    Stream RAG response via Server-Sent Events (SSE).
    Supports Groq (near-instant ~0.3s) and Gemini (Google) with auto-fallback.
    Cached: identical repeated queries return instantly via SSE (<10ms).
    """
    t_start = time.perf_counter()

    def event_stream():
        ck = _cache_key(body.query, body.top_k)

        # 1. Fast Cache Check: If query was asked before, yield immediately (<10ms)
        if ck in _rag_cache:
            _rag_cache.move_to_end(ck)
            cached_data = _rag_cache[ck]
            logger.info("[rag-stream] Cache HIT for: %.60s", body.query)
            yield f"event: init\ndata: {json.dumps({'sources': cached_data['sources'], 'search_ms': 0})}\n\n"
            yield f"event: token\ndata: {json.dumps({'token': cached_data['answer']})}\n\n"
            yield f"event: done\ndata: {json.dumps({'model': cached_data['model'], 'metrics': {'search_ms': 0, 'llm_ms': 0, 'total_ms': 5, 'cached': True}})}\n\n"
            return

        chunks_to_use, sources, search_ms, target_result = _retrieve_context(body.query, body.top_k)

        sources_payload = [
            {"filename": s.filename, "path": s.path, "snippet": s.snippet, "score": s.score, "file_id": s.file_id, "extension": s.extension}
            for s in sources
        ]
        yield f"event: init\ndata: {json.dumps({'sources': sources_payload, 'search_ms': search_ms})}\n\n"

        if not chunks_to_use or target_result is None:
            no_docs_msg = "No relevant documents found in the index. Make sure your folders are added and indexed in Setup."
            yield f"event: token\ndata: {json.dumps({'token': no_docs_msg})}\n\n"
            yield f"event: done\ndata: {json.dumps({'model': 'none', 'metrics': {'search_ms': search_ms, 'llm_ms': 0, 'total_ms': search_ms}})}\n\n"
            return

        pref_provider = (body.provider or "auto").lower()
        groq_key = _get_groq_key(body.groq_api_key)
        candidate_gemini_keys = _get_candidate_keys(body.api_key)

        use_groq = False
        use_gemini = False

        if pref_provider == "groq":
            use_groq = True
        elif pref_provider == "gemini":
            use_gemini = True
        else:  # "auto"
            if groq_key:
                use_groq = True
                use_gemini = True
            else:
                use_gemini = True

        if not groq_key and not candidate_gemini_keys:
            top_snippet = chunks_to_use[0]["text"] if chunks_to_use else target_result.top_chunk_text
            fallback_msg = (
                f"**API Key Required**: Please configure a Groq or Gemini API key in Setup.\n\n"
                f"**Direct excerpt from `{target_result.filename}`:**\n> {top_snippet.strip()}"
            )
            yield f"event: token\ndata: {json.dumps({'token': fallback_msg})}\n\n"
            yield f"event: done\ndata: {json.dumps({'model': 'direct-extract-fallback', 'metrics': {'search_ms': search_ms, 'llm_ms': 0, 'total_ms': search_ms}})}\n\n"
            return

        prompt = _build_prompt(body.query, chunks_to_use)
        model_used = "groq/llama-3.3-70b" if use_groq else "gemini-flash-lite-latest"
        t_llm_start = time.perf_counter()

        token_queue: queue.Queue = queue.Queue()

        def _run_llm():
            try:
                # 1. Try Groq first if enabled (ultra-fast LPU, ~0.3s TTFT)
                if use_groq and groq_key:
                    try:
                        for token_text, m_name in _call_groq_stream(prompt, groq_key):
                            token_queue.put(("token", token_text, m_name))
                        token_queue.put(("done",))
                        return
                    except Exception as groq_err:
                        logger.warning("[rag-stream] Groq failed, falling back to Gemini: %s", groq_err)
                        if not use_gemini or not candidate_gemini_keys:
                            raise groq_err

                # 2. Fallback to Gemini if Groq disabled or failed
                if use_gemini and candidate_gemini_keys:
                    for token_text, m_name in _call_gemini_stream(prompt, candidate_gemini_keys):
                        token_queue.put(("token", token_text, m_name))
                    token_queue.put(("done",))
                else:
                    raise RuntimeError("No configured AI key for requested provider.")
            except Exception as exc:
                token_queue.put(("error", exc))

        thread = threading.Thread(target=_run_llm, daemon=True)
        thread.start()

        full_tokens = []

        while True:
            try:
                item = token_queue.get(timeout=1.0)
            except queue.Empty:
                elapsed = round(time.perf_counter() - t_llm_start, 1)
                yield f"event: heartbeat\ndata: {json.dumps({'elapsed': elapsed})}\n\n"
                continue

            if item[0] == "token":
                model_used = item[2]
                full_tokens.append(item[1])
                yield f"event: token\ndata: {json.dumps({'token': item[1]})}\n\n"
            elif item[0] == "done":
                llm_ms = round((time.perf_counter() - t_llm_start) * 1000, 1)
                total_ms = round((time.perf_counter() - t_start) * 1000, 1)

                completed_answer = "".join(full_tokens).strip()
                if completed_answer:
                    _rag_cache[ck] = {
                        "answer": completed_answer,
                        "sources": sources_payload,
                        "model": model_used,
                    }
                    if len(_rag_cache) > _RAG_CACHE_MAX:
                        _rag_cache.popitem(last=False)
                    logger.info("[rag-stream] Cached response for: %.60s (%.1fs)", body.query, total_ms / 1000)

                yield f"event: done\ndata: {json.dumps({'model': model_used, 'metrics': {'search_ms': search_ms, 'llm_ms': llm_ms, 'total_ms': total_ms}})}\n\n"
                break
            elif item[0] == "error":
                exc = item[1]
                logger.error("[rag-stream] Error: %s", exc)
                err_msg = f"\n\n**API Error**: {exc}"
                yield f"event: token\ndata: {json.dumps({'token': err_msg})}\n\n"
                total_ms = round((time.perf_counter() - t_start) * 1000, 1)
                yield f"event: done\ndata: {json.dumps({'model': 'error-fallback', 'metrics': {'search_ms': search_ms, 'llm_ms': 0, 'total_ms': total_ms}})}\n\n"
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disables nginx/proxy response buffering
            "Connection": "keep-alive",
        },
    )
