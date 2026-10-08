"""
RAG (Retrieval-Augmented Generation) endpoint powered by Google Gemini API.

POST /rag
  - Retrieves top-k semantically relevant chunks from FAISS
  - Builds grounded context string from retrieved snippets
  - Queries Google Gemini 1.5 Flash
  - Returns model answer with document citations
"""

import logging
import os
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter

from schemas.rag import RAGRequest, RAGResponse, RAGSource
from services.search_service import search

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])


def _find_gemini_key(user_key: Optional[str] = None) -> Optional[str]:
    """
    Dynamically find Gemini API key from:
    1. Direct request body
    2. OS Environment variable GEMINI_API_KEY
    3. backend/.env, project root .env, or frontend/.env
    """
    if user_key and user_key.strip():
        return user_key.strip()

    env_key = os.environ.get("GEMINI_API_KEY")
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
                        if k in ("GEMINI_API_KEY", "VITE_GEMINI_API_KEY") and v:
                            return v
            except Exception:
                pass
    return None


def _build_context(results) -> str:
    """Concatenate retrieved chunks into a numbered context block."""
    parts = []
    for i, r in enumerate(results, start=1):
        parts.append(f"[{i}] {r.filename} (Page {r.top_page})\n{r.top_chunk_text}")
    return "\n\n".join(parts)


def _call_gemini(prompt: str, api_key: str) -> str:
    """
    Query Google Gemini API with fallback from google.genai to direct REST endpoint.
    """
    api_key = api_key.strip()

    # 1. Try google.genai SDK
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
        )
        if response.text and response.text.strip():
            return response.text.strip()
    except Exception as exc:
        logger.warning("[rag] google.genai client exception (%s), falling back to REST...", exc)

    # 2. Direct Google Generative Language REST API
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1024,
        },
    }
    with httpx.Client(timeout=45.0) as client:
        res = client.post(url, json=payload)
        if res.status_code != 200:
            err_msg = res.text
            try:
                err_data = res.json()
                if "error" in err_data and "message" in err_data["error"]:
                    err_msg = err_data["error"]["message"]
            except Exception:
                pass
            raise RuntimeError(f"Gemini API ({res.status_code}): {err_msg}")

        data = res.json()
        candidates = data.get("candidates", [])
        if candidates and "content" in candidates[0]:
            parts = candidates[0]["content"].get("parts", [])
            if parts and "text" in parts[0]:
                return parts[0]["text"].strip()
        raise RuntimeError("Gemini returned an empty response.")


@router.post("/rag", response_model=RAGResponse)
def rag_query(body: RAGRequest):
    """
    Answer a natural language question using document chunks + Gemini API.
    """
    results = search(query=body.query, top_k=body.top_k)

    sources = [
        RAGSource(
            filename=r.filename,
            path=r.path,
            snippet=r.top_chunk_text,
            score=r.score,
        )
        for r in results
    ]

    if not results:
        return RAGResponse(
            query=body.query,
            answer="No relevant documents found in the index. Make sure your folders are added and indexed in Setup before asking questions.",
            sources=[],
            model="none",
        )

    api_key = _find_gemini_key(body.api_key)
    if not api_key:
        return RAGResponse(
            query=body.query,
            answer="Gemini API Key is not configured. Please paste your Gemini API key in the 'Setup' tab under Gemini AI, or set GEMINI_API_KEY in .env.",
            sources=sources,
            model="none",
        )

    context = _build_context(results)
    prompt = (
        "You are an intelligent document assistant in Memoria.\n"
        "Answer the question clearly and factually using ONLY the provided document excerpts.\n"
        "Cite your sources using [1], [2], etc. referencing the numbered excerpts.\n"
        "If the excerpts do not contain enough information to answer, state that clearly.\n\n"
        f"Document Excerpts:\n{context}\n\n"
        f"Question: {body.query}\n\n"
        "Answer:"
    )

    try:
        answer = _call_gemini(prompt, api_key)
        return RAGResponse(
            query=body.query,
            answer=answer,
            sources=sources,
            model="Gemini 1.5 Flash (Google API)",
        )
    except Exception as exc:
        logger.error("[rag] Gemini error: %s", exc)
        return RAGResponse(
            query=body.query,
            answer=f"Gemini API Error: {exc}",
            sources=sources,
            model="none",
        )
