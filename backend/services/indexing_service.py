"""
Folder scanning service.

Scope for this iteration: walk a folder tree, find supported files, record
their metadata + content hash in SQLite. This deliberately does NOT extract
text, chunk, or embed anything — that is Iterations 5+. A file with
status='pending' here means "known to exist, not yet processed."

Why this is a service (not logic inside the API router):
  The router should only handle HTTP concerns: parse the request, call this
  service, serialise the response. If we later move scanning to a background
  task queue, only this file changes — the router stays the same.

Concurrency note (for Iteration 3 when watchdog is added):
  This function is synchronous and runs in the FastAPI worker thread right
  now. That's fine because we're only stat()-ing + hashing files (fast).
  Once text extraction is added (slow, I/O-heavy), scanning will need to
  move into a background thread or async task queue. The design anticipates
  this: `scan_folder` is already a plain function that can be submitted
  to a thread pool without any refactor.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from db.repositories import FileRepository
from processors.file_utils import compute_content_hash, is_supported


def _iso(ts: float) -> str:
    """Convert a POSIX timestamp to an ISO-8601 UTC string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def scan_folder(folder_id: int, folder_path: str, file_repo: FileRepository) -> dict:
    """
    Recursively walk `folder_path`, upsert a `files` row for every supported
    file found, and return summary counts.

    Returns:
        {
          "new_files":       int,   # files not previously in the DB
          "updated_files":   int,   # files whose content hash changed
          "unchanged_files": int,   # files already indexed with same hash
          "skipped_files":   int,   # unsupported extension or unreadable
        }

    These counts go straight into the API response, so the caller sees
    exactly what the scan did — useful for "I just added a folder, what
    happened?" without a separate status poll.
    """
    new_count = 0
    updated_count = 0
    unchanged_count = 0
    skipped_count = 0

    root = Path(folder_path)

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden directories (.git, .cache, __pycache__, etc.) in-place
        # so os.walk doesn't descend into them at all — pruning beats filtering.
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]

        for name in filenames:
            if name.startswith("."):
                continue

            file_path = Path(dirpath) / name

            if not is_supported(file_path):
                skipped_count += 1
                continue

            try:
                stat = file_path.stat()
                content_hash = compute_content_hash(file_path)
            except OSError:
                # Unreadable file (permissions issue, broken symlink, file
                # disappeared between the directory listing and stat()).
                # Skip and count it rather than aborting the whole scan.
                skipped_count += 1
                continue

            _row, status = file_repo.upsert(
                folder_id=folder_id,
                filename=name,
                path=str(file_path),
                extension=file_path.suffix.lower(),
                size_bytes=stat.st_size,
                created_at=_iso(stat.st_ctime),
                modified_at=_iso(stat.st_mtime),
                content_hash=content_hash,
            )

            if status == "new":
                new_count += 1
            elif status == "updated":
                updated_count += 1
            else:  # "unchanged"
                unchanged_count += 1

    return {
        "new_files": new_count,
        "updated_files": updated_count,
        "unchanged_files": unchanged_count,
        "skipped_files": skipped_count,
    }
