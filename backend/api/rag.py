"""
RAG (Retrieval-Augmented Generation) endpoint.

POST /rag
  - Retrieves the top-k semantically relevant chunks from the FAISS index
  - Builds a context string and sends it to Gemini API (if GEMINI_API_KEY is set)
    or a local Ollama instance as a fallback.
  - Returns the LLM answer along with the source documents used
"""

import json
import logging
import os

import httpx
from fastapi import APIRouter

from schemas.rag import RAGRequest, RAGResponse, RAGSource
from services.search_service import search

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])

OLLAMA_URL = "http://localhost:11434/api/generate"
PREFERRED_MODELS = ["llama3.2", "mistral", "llama3.2:1b", "qwen2.5:0.5b"]
OLLAMA_TIMEOUT = 120  # seconds — LLM inference can be slow on CPU

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


def _build_context(results) -> str:
    """
    Concatenate retrieved chunks into a numbered context block.
    Each entry includes the filename so the model can cite sources.
    """
    parts = []
    for i, r in enumerate(results, start=1):
        parts.append(f"[{i}] {r.filename}\n{r.top_chunk_text}")
    return "\n\n".join(parts)


def _call_gemini(prompt: str) -> str:
    """
    Call Google's Gemini API using the new google-genai SDK.
    Supports both AQ. auth keys and AIzaSy API keys from Google AI Studio.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY.strip())
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
        )
        return response.text.strip()
    except ImportError:
        raise RuntimeError(
            "google-genai not installed. Run: pip install google-genai"
        )


def _call_ollama(model: str, prompt: str) -> str:
    """
    Send a synchronous, non-streaming request to Ollama.
    Returns the response text or raises an exception.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
        response = client.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()


def _try_ollama_models(prompt: str) -> tuple[str, str]:
    """
    Try each model in PREFERRED_MODELS in order.
    Returns (answer, model_name) for the first model that succeeds.
    Raises the last exception if all fail.
    """
    last_exc: Exception | None = None
    for model in PREFERRED_MODELS:
        try:
            answer = _call_ollama(model, prompt)
            return answer, model
        except httpx.ConnectError as e:
            # Ollama isn't running at all — no point trying other models
            raise e
        except httpx.HTTPStatusError as e:
            # 404 = model not found, try the next one
            if e.response.status_code == 404:
                logger.info("[rag] Model '%s' not found, trying next", model)
                last_exc = e
                continue
            raise e
        except Exception as e:
            last_exc = e
            continue
    raise last_exc  # type: ignore[misc]


@router.post("/rag", response_model=RAGResponse)
def rag_query(body: RAGRequest):
    """
    Answer a natural language question using local document context.
    """
    # --- 1. Retrieve relevant chunks ---
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

    # --- 2. Build context ---
    if not results:
        return RAGResponse(
            query=body.query,
            answer="No relevant documents found in the index. "
                   "Make sure files have been indexed before querying.",
            sources=[],
            model="none",
        )

    context = _build_context(results)
    prompt = (
        "You are a helpful assistant. Answer the question below using ONLY "
        "the provided document excerpts. If the answer is not in the excerpts, "
        "say so clearly.\n\n"
        f"Documents:\n{context}\n\n"
        f"Question: {body.query}\n\n"
        "Answer:"
    )

    # --- 3. Call LLM (Gemini if key exists, else Ollama) ---
    try:
        if GEMINI_API_KEY:
            answer = _call_gemini(prompt)
            model_used = "Gemini 1.5 Flash (API)"
        else:
            answer, model_used = _try_ollama_models(prompt)
    except httpx.ConnectError:
        logger.warning("[rag] Ollama not reachable at %s", OLLAMA_URL)
        return RAGResponse(
            query=body.query,
            answer="Ollama not running and no GEMINI_API_KEY provided. Start Ollama or provide a Gemini API key.",
            sources=sources,
            model="none",
        )
    except Exception as exc:
        logger.error("[rag] LLM error: %s", exc)
        return RAGResponse(
            query=body.query,
            answer=f"LLM error: {exc}",
            sources=sources,
            model="none",
        )

    # --- 4. Return answer + sources ---
    return RAGResponse(
        query=body.query,
        answer=answer,
        sources=sources,
        model=model_used,
    )
