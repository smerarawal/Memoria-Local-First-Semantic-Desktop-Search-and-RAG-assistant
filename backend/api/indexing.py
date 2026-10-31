"""
API router for indexing status and control.

Endpoints:
  GET  /index/status        — watcher state + file counts by status
  POST /index/pause         — pause the file watcher (disable all watches)
  POST /index/resume        — resume the file watcher

Why these endpoints:
  The spec (section 9) requires the user to be able to "Pause indexing" and
  "Stop monitoring" from the UI. The watcher service owns that state; this
  router exposes it over HTTP so the React frontend can reflect it.

  POST /index/rebuild and DELETE /index are deferred to Iteration 5+,
  because "rebuild" means "re-extract, re-chunk, re-embed" — none of which
  exist yet. Adding stub endpoints that do nothing would be misleading, so
  they're intentionally absent until there's real work to do.
"""

import sqlite3

from fastapi import APIRouter, Depends

from db.database import get_db
from schemas.indexing import IndexStatusResponse
from services.file_watcher_service import watcher_service

router = APIRouter(prefix="/index", tags=["index"])


def _file_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Aggregate file row counts by status in a single query.
    Returns a dict with keys: total, pending, indexed, failed, deleted.
    """
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS cnt
        FROM files
        GROUP BY status
        """
    ).fetchall()

    counts = {"pending": 0, "indexed": 0, "failed": 0, "deleted": 0}
    for row in rows:
        status = row["status"]
        if status in counts:
            counts[status] = row["cnt"]

    total = sum(counts.values())
    return {**counts, "total": total}


@router.get("/status", response_model=IndexStatusResponse)
def index_status(conn: sqlite3.Connection = Depends(get_db)):
    """
    Returns the current state of the watcher and a snapshot of file
    processing status counts from SQLite.

    This is what the Settings panel uses to display:
      ● Monitoring: ON
      3 folders watched
      42 files indexed / 5 pending
    """
    watcher_snap = watcher_service.status()
    counts = _file_counts(conn)

    return IndexStatusResponse(
        watcher_running=watcher_snap["running"],
        watched_folders=watcher_snap["watched_folders"],
        watched_folder_ids=watcher_snap["watched_folder_ids"],
        total_files=counts["total"],
        pending_files=counts["pending"],
        indexed_files=counts["indexed"],
        failed_files=counts["failed"],
        deleted_files=counts["deleted"],
    )


@router.post("/pause", status_code=200)
def pause_indexing():
    """
    Pause the file watcher — stop monitoring all folders for changes.
    Existing index data is preserved; new file changes won't be picked up
    until the watcher is resumed.
    """
    watcher_service.stop()
    return {"message": "File watcher paused.", "watcher_running": False}


@router.post("/resume", status_code=200)
def resume_indexing():
    """
    Resume the file watcher after a pause. Re-schedules watches for all
    enabled folders currently in the database.
    """
    watcher_service.start()
    snap = watcher_service.status()
    return {
        "message": "File watcher resumed.",
        "watcher_running": snap["running"],
        "watched_folders": snap["watched_folders"],
    }


@router.post("", status_code=200)
@router.post("/rebuild", status_code=200)
@router.post("/scan", status_code=200)
def trigger_indexing(conn: sqlite3.Connection = Depends(get_db)):
    """
    Trigger manual scan and indexing for all watched folders.
    1. Rescans all watched folders for newly added or modified files.
    2. Processes all pending files through extraction, chunking, embedding, and FAISS indexing.
    """
    from pathlib import Path
    from db.repositories import FileRepository, FolderRepository
    from services.indexing_service import scan_folder
    from services.document_service import process_pending_files

    folder_repo = FolderRepository(conn)
    file_repo = FileRepository(conn)
    watched_folders = [f for f in folder_repo.list_all() if f["enabled"]]

    total_new = 0
    total_updated = 0
    for f in watched_folders:
        folder_path = Path(f["path"])
        if folder_path.is_dir():
            summary = scan_folder(
                folder_id=f["folder_id"],
                folder_path=f["path"],
                file_repo=file_repo,
            )
            total_new += summary.get("new_files", 0)
            total_updated += summary.get("updated_files", 0)

    # Trigger background processing for all pending files without blocking HTTP response
    import threading
    threading.Thread(target=process_pending_files, daemon=True, name="manual-index-worker").start()

    counts = _file_counts(conn)
    return {
        "message": "Indexing started.",
        "scanned_folders": len(watched_folders),
        "new_files": total_new,
        "updated_files": total_updated,
        "pending_files": counts["pending"],
    }
