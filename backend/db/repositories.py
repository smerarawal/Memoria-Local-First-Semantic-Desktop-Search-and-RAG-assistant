"""
Repository layer: every SQL statement in the app lives here.

Why bother with this layer for something as simple as SQLite:
Once search/RAG services need to query files and chunks, they should call
`FileRepository.get(id)` and not care whether that's backed by SQLite,
a different DB, or a cache later. It also means there's exactly one place
to fix if a query is wrong, instead of the same SELECT duplicated across
api/services files.

This module owns three repositories:
  FolderRepository  — CRUD on the `folders` table
  FileRepository    — CRUD + upsert logic on the `files` table
  ChunkRepository   — CRUD on the `chunks` table (added Iteration 4)
"""

import sqlite3
from typing import Optional


class FolderRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create(self, path: str) -> sqlite3.Row:
        cur = self.conn.execute(
            "INSERT INTO folders (path) VALUES (?)", (path,)
        )
        self.conn.commit()
        return self.get(cur.lastrowid)

    def get(self, folder_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM folders WHERE folder_id = ?", (folder_id,)
        ).fetchone()

    def get_by_path(self, path: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM folders WHERE path = ?", (path,)
        ).fetchone()

    def list_all(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM folders ORDER BY created_at"
        ).fetchall()

    def delete(self, folder_id: int) -> None:
        # ON DELETE CASCADE on files.folder_id handles cleanup of files rows
        # (and chunks.file_id cascades further to chunks). FAISS cleanup for
        # indexed files must be done explicitly before calling this — the
        # folders router handles that via document_service.
        self.conn.execute("DELETE FROM folders WHERE folder_id = ?", (folder_id,))
        self.conn.commit()


class FileRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_by_path(self, path: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM files WHERE path = ?", (path,)
        ).fetchone()

    def get(self, file_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM files WHERE file_id = ?", (file_id,)
        ).fetchone()

    def list_all(self, folder_id: Optional[int] = None) -> list[sqlite3.Row]:
        if folder_id is not None:
            return self.conn.execute(
                "SELECT * FROM files WHERE folder_id = ? ORDER BY filename",
                (folder_id,),
            ).fetchall()
        return self.conn.execute("SELECT * FROM files ORDER BY filename").fetchall()

    def list_by_status(self, status: str) -> list[sqlite3.Row]:
        """Return all files with a given status. Used by the processing worker."""
        return self.conn.execute(
            "SELECT * FROM files WHERE status = ? ORDER BY file_id",
            (status,),
        ).fetchall()

    def update_status(
        self,
        file_id: int,
        status: str,
        indexed_at: Optional[str] = None,
    ) -> None:
        """Update a file's processing status (and optionally indexed_at)."""
        if indexed_at:
            self.conn.execute(
                "UPDATE files SET status = ?, indexed_at = ? WHERE file_id = ?",
                (status, indexed_at, file_id),
            )
        else:
            self.conn.execute(
                "UPDATE files SET status = ? WHERE file_id = ?",
                (status, file_id),
            )
        self.conn.commit()

    def upsert(
        self,
        folder_id: int,
        filename: str,
        path: str,
        extension: str,
        size_bytes: int,
        created_at: Optional[str],
        modified_at: Optional[str],
        content_hash: str,
    ) -> tuple[sqlite3.Row, str]:
        """
        Insert a new file row, or update an existing one IF its content hash
        changed. Returns (row, status) where status is one of:
          "new"       — file was not previously known
          "updated"   — file existed but its hash changed; reset to 'pending'
          "unchanged" — same hash, nothing written

        Unchanged files are left entirely alone — status/indexed_at stay as
        they were, since nothing downstream needs to redo work.

        Note: when status == "updated", we do NOT delete the old chunks here.
        That cleanup belongs in the extraction step (future iteration), which
        is also responsible for re-embedding. Doing it here would mean we
        delete chunks before the extractor is ready to recreate them, leaving
        a gap window where the file has no indexed content.
        """
        existing = self.get_by_path(path)

        if existing is None:
            cur = self.conn.execute(
                """INSERT INTO files
                   (folder_id, filename, path, extension, size_bytes,
                    created_at, modified_at, content_hash, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (folder_id, filename, path, extension, size_bytes,
                 created_at, modified_at, content_hash),
            )
            self.conn.commit()
            return self.get(cur.lastrowid), "new"

        if existing["content_hash"] == content_hash:
            return existing, "unchanged"

        # Hash changed: reset to 'pending' so the processing worker re-extracts.
        self.conn.execute(
            """UPDATE files
               SET size_bytes = ?, modified_at = ?, content_hash = ?, status = 'pending'
               WHERE file_id = ?""",
            (size_bytes, modified_at, content_hash, existing["file_id"]),
        )
        self.conn.commit()
        return self.get(existing["file_id"]), "updated"

    def mark_deleted(self, file_id: int) -> None:
        """Soft-delete: mark status='deleted'. Hard cleanup is done by
        the watcher/document_service when they remove chunks from FAISS."""
        self.conn.execute(
            "UPDATE files SET status = 'deleted' WHERE file_id = ?", (file_id,)
        )
        self.conn.commit()


class ChunkRepository:
    """
    CRUD on the `chunks` table.

    The key design point: chunk_id is used as the FAISS vector ID (faiss_id).
    This means a FAISS search result → chunk_id → direct SQLite lookup.
    No secondary mapping table needed.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(
        self,
        file_id: int,
        chunk_index: int,
        page_number: int,
        text: str,
    ) -> int:
        """Insert a chunk row and return the new chunk_id."""
        cur = self.conn.execute(
            """INSERT INTO chunks (file_id, chunk_index, page_number, text)
               VALUES (?, ?, ?, ?)""",
            (file_id, chunk_index, page_number, text),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_faiss_id(self, chunk_id: int, faiss_id: int) -> None:
        """Record the FAISS ID for a chunk (== chunk_id in our design)."""
        self.conn.execute(
            "UPDATE chunks SET faiss_id = ? WHERE chunk_id = ?",
            (faiss_id, chunk_id),
        )
        self.conn.commit()

    def get(self, chunk_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()

    def get_many(self, chunk_ids: list[int]) -> list[sqlite3.Row]:
        """Fetch multiple chunk rows by ID in a single query."""
        if not chunk_ids:
            return []
        placeholders = ",".join("?" * len(chunk_ids))
        return self.conn.execute(
            f"SELECT * FROM chunks WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        ).fetchall()

    def get_faiss_ids_for_file(self, file_id: int) -> list[int]:
        """Return all faiss_ids for chunks belonging to a file."""
        rows = self.conn.execute(
            "SELECT faiss_id FROM chunks WHERE file_id = ? AND faiss_id IS NOT NULL",
            (file_id,),
        ).fetchall()
        return [r["faiss_id"] for r in rows]

    def delete_for_file(self, file_id: int) -> None:
        """Delete all chunk rows for a file (used before re-indexing)."""
        self.conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
        self.conn.commit()
