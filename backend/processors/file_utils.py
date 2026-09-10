"""
File utilities for the processor layer.

Two responsibilities:
  1. is_supported(path)        — decides whether a file extension is one
                                 Memoria knows how to process. This is the
                                 single gating point: add a new extension
                                 here and the scanner + watcher automatically
                                 pick it up.

  2. compute_content_hash(path) — SHA-256 the raw file bytes and return a
                                  hex string. This is how we detect whether
                                  a file has actually changed (spec §11):
                                  same hash → skip reprocessing.

Why SHA-256 over mtime:
  mtime is unreliable — it can be preserved by copy tools, reset by some
  editors, or lie due to filesystem granularity. Hashing the bytes catches
  every real content change and ignores spurious metadata touches.
  The downside is we have to read every file on each scan; for large files
  this is slightly slower than stat(), but for a desktop corpus of documents
  (PDFs, DOCX, TXT) it's negligible and the correctness guarantee is worth it.
"""

import hashlib
from pathlib import Path

# Extensions Memoria can process. Centralised here so the scanner,
# watcher, and future processors all share one source of truth.
# OCR (.png / .jpg) comes later (Iteration 7+ per project plan).
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".docx", ".txt", ".md"}
)


def is_supported(path: Path) -> bool:
    """Return True if this file's extension is in our supported set."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def compute_content_hash(path: Path) -> str:
    """
    Return the SHA-256 hex digest of the file at `path`.
    Reads in 64 KB chunks to avoid loading huge files entirely into RAM.
    Raises OSError if the file cannot be read (caller decides what to do).
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
