"""
FAISS vector index wrapper.

Design decisions documented here (important to understand before modifying):

1. IndexIDMap wrapping IndexFlatIP
   Plain IndexFlatIP assigns sequential integer IDs starting at 0. We can't
   use those IDs to look up chunks in SQLite — we need to store the chunk_id
   as the FAISS ID so a search result directly maps to a DB row.
   IndexIDMap lets us pass our own IDs via add_with_ids().

2. IndexFlatIP (inner product) + L2 normalisation = cosine similarity
   All-MiniLM-L6-v2 produces normalised vectors by default when using
   encode(normalize_embeddings=True). For normalised vectors, inner product
   equals cosine similarity. This is equivalent to IndexFlatL2 with
   normalised vectors but is the standard pattern for cosine similarity in FAISS.

3. Persistence
   The index is saved to disk after every batch of additions so it survives
   server restarts. FAISS doesn't have incremental saves — we rewrite the
   whole file each time, which is fine for a desktop-scale corpus.

4. Deletion
   IndexIDMap supports remove_ids() for hard deletion of specific vectors.
   This is what enables the file deletion pipeline: when watchdog detects a
   deleted file, we remove its chunk vectors from FAISS rather than needing
   a full rebuild.

5. Thread safety
   FAISS is NOT thread-safe for concurrent add/search operations. We protect
   the index with a threading.RLock. Search is read-only and could be
   parallelised with a reader-writer lock, but an RLock is simpler and
   sufficient for the current load profile (one desktop user).
"""

import logging
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from config.settings import FAISS_INDEX_PATH

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 output dimension


class FaissIndex:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._index = None  # Loaded lazily on first access
        self._dim = EMBEDDING_DIM

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load or create the index if not already in memory."""
        if self._index is not None:
            return

        import faiss  # Deferred import so the app boots without faiss installed

        index_path = Path(FAISS_INDEX_PATH)
        if index_path.exists():
            try:
                self._index = faiss.read_index(str(index_path))
                logger.info(
                    "[faiss] Loaded index from disk: %d vectors", self._index.ntotal
                )
                return
            except Exception as exc:
                logger.warning("[faiss] Failed to load index from disk: %s — creating new", exc)

        # Create fresh index: IndexIDMap wraps a flat inner-product index
        flat = faiss.IndexFlatIP(self._dim)
        self._index = faiss.IndexIDMap(flat)
        logger.info("[faiss] Created new empty index (dim=%d)", self._dim)

    def _save(self) -> None:
        """Persist the index to disk."""
        import faiss
        try:
            faiss.write_index(self._index, str(FAISS_INDEX_PATH))
        except Exception as exc:
            logger.error("[faiss] Failed to save index: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, vectors: np.ndarray, ids: np.ndarray) -> None:
        """
        Add vectors to the index.

        Args:
            vectors: float32 array of shape (N, dim). Should already be
                     L2-normalised (sentence-transformers does this when
                     normalize_embeddings=True).
            ids:     int64 array of shape (N,) — the chunk_ids from SQLite.
        """
        import faiss
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        ids = np.ascontiguousarray(ids, dtype=np.int64)

        with self._lock:
            self._ensure_loaded()
            faiss.normalize_L2(vectors)  # Idempotent if already normalised
            self._index.add_with_ids(vectors, ids)
            self._save()

        logger.info("[faiss] Added %d vectors. Total: %d", len(ids), self.ntotal)

    def search(self, query_vector: np.ndarray, k: int = 10) -> list[tuple[int, float]]:
        """
        Find the k nearest neighbours to query_vector.

        Args:
            query_vector: float32 array of shape (dim,) or (1, dim).
            k:            number of results to return.

        Returns:
            List of (chunk_id, score) tuples, sorted descending by score.
            Scores are cosine similarities in [0, 1] for normalised vectors.
            Results with FAISS sentinel ID -1 (no result) are filtered out.
        """
        import faiss
        if query_vector.ndim == 1:
            query_vector = query_vector.reshape(1, -1)
        query_vector = np.ascontiguousarray(query_vector, dtype=np.float32)

        with self._lock:
            self._ensure_loaded()
            if self._index.ntotal == 0:
                return []

            faiss.normalize_L2(query_vector)
            k_actual = min(k, self._index.ntotal)
            distances, ids = self._index.search(query_vector, k_actual)

        results = [
            (int(cid), float(score))
            for cid, score in zip(ids[0], distances[0])
            if cid != -1  # FAISS uses -1 as a sentinel for "no result"
        ]
        return results

    def remove(self, chunk_ids: list[int]) -> None:
        """
        Remove vectors by their chunk_id (FAISS ID).
        Used when a file is deleted or re-indexed.
        """
        if not chunk_ids:
            return

        import faiss
        ids_array = np.array(chunk_ids, dtype=np.int64)
        selector = faiss.IDSelectorArray(ids_array)

        with self._lock:
            self._ensure_loaded()
            removed = self._index.remove_ids(selector)
            self._save()

        logger.info("[faiss] Removed %d vectors. Total: %d", removed, self.ntotal)

    @property
    def ntotal(self) -> int:
        """Total number of vectors currently in the index."""
        with self._lock:
            self._ensure_loaded()
            return self._index.ntotal


# Module-level singleton — shared across the embedding service,
# document service, and search service.
faiss_index = FaissIndex()
