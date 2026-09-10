"""
SQLite connection management.

Two decisions made here that matter later and are annoying to retrofit:

1. WAL mode (journal_mode=WAL). The file watcher runs on a background
   thread while FastAPI serves requests on another. Default SQLite
   journaling locks the whole database on writes, which will throw
   "database is locked" errors under that concurrency. WAL lets reads
   and writes coexist much better.

2. Connections are created per-request via a generator (get_db), not
   shared globally. sqlite3 connections are not safe to share across
   threads by default; letting FastAPI's dependency injection open/close
   one per request avoids that whole class of bugs.
"""

import sqlite3
from contextlib import contextmanager

from config.settings import SQLITE_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    """FastAPI dependency: yields a connection, closes it after the request."""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def db_session():
    """Non-FastAPI context manager, for use in startup code, scripts, tests."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with db_session() as conn:
        conn.executescript(SCHEMA_SQL)


# Schema matches section 20 of the project spec.
# NOTE: chunks/embeddings are not populated until Iteration 4 (embeddings +
# FAISS). They're created now so the schema is stable and we're not doing
# a migration later just to add a table we already knew we needed.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS folders (
    folder_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL UNIQUE,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS files (
    file_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id     INTEGER NOT NULL REFERENCES folders(folder_id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    path          TEXT NOT NULL UNIQUE,
    extension     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    created_at    TEXT,
    modified_at   TEXT,
    content_hash  TEXT NOT NULL,
    indexed_at    TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'indexed', 'failed', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder_id);
CREATE INDEX IF NOT EXISTS idx_files_hash ON files(content_hash);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id      INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    page_number  INTEGER,
    text         TEXT NOT NULL,
    faiss_id     INTEGER UNIQUE,
    embedding_model TEXT,
    embedding_dim   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_chunks_faiss_id ON chunks(faiss_id);
"""
