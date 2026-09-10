"""
Document service — orchestrates the full processing pipeline for a single file.

Pipeline:
  File (path + extension)
    ↓ extract_*()         → [(page_num, text)]
    ↓ chunk_pages()       → [(chunk_index, page_num, text)]
    ↓ embedding_service   → float32 array (N, 384)
    ↓ ChunkRepository     → chunk rows with chunk_ids
    ↓ faiss_index.add()   → vectors stored with chunk_id as FAISS ID
    ↓ FileRepository      → status = 'indexed'

Re-indexing (file modified):
  When a file's hash changes, the watcher sets status='pending'.
  process_file() detects existing chunks for that file, removes them from
  both SQLite and FAISS before inserting the new ones. This is the "update
  FAISS" step called out in spec section 11.

This module also exposes process_pending_files() which is called:
  - On app startup (picks up any files left as 'pending' from a previous session)
  - Via POST /index (manual trigger from the UI)
  - By a background worker thread (added here as a simple loop)
"""

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from db.database import db_session
from db.repositories import ChunkRepository, FileRepository
from processors.chunker import chunk_pages
from processors.docx_processor import extract_docx
from processors.pdf_processor import extract_pdf
from processors.txt_processor import extract_text
from services.embedding_service import embedding_service
from vector.faiss_index import faiss_index

import numpy as np

logger = logging.getLogger(__name__)

# How often the background worker checks for pending files (seconds)
_WORKER_POLL_INTERVAL = 10


def _extract(path: Path, extension: str):
    """Route to the correct extractor based on extension."""
    if extension == ".pdf":
        return extract_pdf(path)
    elif extension == ".docx":
        return extract_docx(path)
    elif extension in (".txt", ".md"):
        return extract_text(path)
    return None


def process_file(file_id: int) -> str:
    """
    Run the full extraction → chunking → embedding → indexing pipeline for
    one file. Returns the new status: 'indexed' or 'failed'.

    Thread-safe: opens its own DB connection, uses the module-level singletons
    for embedding_service and faiss_index (both internally thread-safe).
    """
    with db_session() as conn:
        file_repo = FileRepository(conn)
        chunk_repo = ChunkRepository(conn)

        file_row = file_repo.get(file_id)
        if file_row is None:
            logger.warning("[doc] process_file: file_id=%d not found", file_id)
            return "failed"

        path = Path(file_row["path"])
        extension = file_row["extension"]
        filename = file_row["filename"]

        logger.info("[doc] Processing: %s (file_id=%d)", filename, file_id)

        # 1. Extract text
        pages = _extract(path, extension)
        if pages is None:
            logger.warning("[doc] Extraction failed for %s", filename)
            file_repo.update_status(file_id, "failed")
            return "failed"

        # 2. Chunk
        chunks = chunk_pages(pages)
        if not chunks:
            logger.warning("[doc] No text extracted from %s", filename)
            file_repo.update_status(file_id, "failed")
            return "failed"

        # 3. Remove old chunks (for re-indexing scenario)
        old_faiss_ids = chunk_repo.get_faiss_ids_for_file(file_id)
        if old_faiss_ids:
            faiss_index.remove(old_faiss_ids)
            chunk_repo.delete_for_file(file_id)
            logger.info("[doc] Removed %d old chunks for file_id=%d", len(old_faiss_ids), file_id)

        # 4. Generate embeddings
        texts = [c[2] for c in chunks]
        try:
            vectors = embedding_service.embed(texts)
        except Exception as exc:
            logger.error("[doc] Embedding failed for %s: %s", filename, exc)
            file_repo.update_status(file_id, "failed")
            return "failed"

        # 5. Insert chunk rows (get chunk_ids back)
        chunk_ids = []
        for (chunk_index, page_num, text), vector in zip(chunks, vectors):
            chunk_id = chunk_repo.insert(
                file_id=file_id,
                chunk_index=chunk_index,
                page_number=page_num,
                text=text,
            )
            chunk_ids.append(chunk_id)

        # 6. Update faiss_id on each chunk row, then add to FAISS
        #    We use the chunk_id as the FAISS ID so search results map
        #    directly to DB rows without a separate lookup table.
        for cid in chunk_ids:
            chunk_repo.set_faiss_id(cid, cid)  # faiss_id == chunk_id

        ids_array = np.array(chunk_ids, dtype=np.int64)
        faiss_index.add(vectors, ids_array)

        # 7. Mark file as indexed
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        file_repo.update_status(file_id, "indexed", indexed_at=now_iso)

        logger.info(
            "[doc] Indexed %s: %d chunks, FAISS total=%d",
            filename, len(chunk_ids), faiss_index.ntotal,
        )
        return "indexed"


def process_pending_files() -> dict:
    """
    Process all files currently in status='pending'.
    Returns summary counts. Called at startup and via POST /index.
    """
    with db_session() as conn:
        file_repo = FileRepository(conn)
        pending = file_repo.list_by_status("pending")

    if not pending:
        logger.info("[doc] No pending files to process.")
        return {"processed": 0, "indexed": 0, "failed": 0}

    logger.info("[doc] Processing %d pending file(s)...", len(pending))
    indexed_count = 0
    failed_count = 0

    for row in pending:
        status = process_file(row["file_id"])
        if status == "indexed":
            indexed_count += 1
        else:
            failed_count += 1

    return {
        "processed": len(pending),
        "indexed": indexed_count,
        "failed": failed_count,
    }


# ------------------------------------------------------------------
# Background worker thread
# ------------------------------------------------------------------

_worker_stop_event = threading.Event()


def _worker_loop() -> None:
    """
    Poll for pending files every _WORKER_POLL_INTERVAL seconds.
    Runs on its own daemon thread, started by start_background_worker().
    """
    logger.info("[doc] Background worker started (poll interval=%ds)", _WORKER_POLL_INTERVAL)
    while not _worker_stop_event.wait(timeout=_WORKER_POLL_INTERVAL):
        try:
            result = process_pending_files()
            if result["processed"] > 0:
                logger.info("[doc] Worker batch: %s", result)
        except Exception as exc:
            logger.error("[doc] Worker error: %s", exc)
    logger.info("[doc] Background worker stopped")


def start_background_worker() -> None:
    """Start the background processing thread. Called once from app startup."""
    _worker_stop_event.clear()
    t = threading.Thread(target=_worker_loop, name="memoria-doc-worker", daemon=True)
    t.start()


def stop_background_worker() -> None:
    """Signal the worker to stop. Called from app shutdown."""
    _worker_stop_event.set()
