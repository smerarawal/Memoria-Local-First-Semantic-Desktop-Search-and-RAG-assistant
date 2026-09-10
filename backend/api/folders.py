"""
API router for folder management.

Endpoints:
  GET    /folders          — list all registered folders
  POST   /folders          — register a new folder, scan it, start watching it
  DELETE /folders/{id}     — stop watching, remove folder (cascades to files+chunks)

Design note — synchronous scan on POST:
  The scan runs synchronously inside the request right now, which is fine
  for Iteration 2-3 because all we're doing is stat()-ing files and hashing
  bytes — maybe a few hundred milliseconds for a typical Documents folder.
  Once text extraction is added (Iteration 5), this will need to move to a
  background task. That refactor is isolated to this router and the service
  layer; nothing else changes.

Design note — 409 on duplicate path:
  SQLite enforces UNIQUE on folders.path, but letting the DB raise an
  IntegrityError and returning a 500 is a bad experience. We check for the
  duplicate explicitly and return 409 Conflict with a readable message.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from db.database import get_db
from db.repositories import FileRepository, FolderRepository
from schemas.folders import FolderCreateRequest, FolderCreateResponse, FolderResponse
from services.file_watcher_service import watcher_service
from services.indexing_service import scan_folder

router = APIRouter(prefix="/folders", tags=["folders"])


@router.get("", response_model=list[FolderResponse])
def list_folders(conn: sqlite3.Connection = Depends(get_db)):
    """Return all registered folders, ordered by registration time."""
    repo = FolderRepository(conn)
    rows = repo.list_all()
    return [dict(r) for r in rows]


@router.post("", response_model=FolderCreateResponse, status_code=201)
def add_folder(
    body: FolderCreateRequest,
    conn: sqlite3.Connection = Depends(get_db),
):
    """
    Register a folder and scan it immediately.

    Pydantic validates that `path` exists on the filesystem before we even
    reach this function (see FolderCreateRequest.path_must_exist). If it
    doesn't exist, FastAPI returns 422 automatically.

    If the folder is already registered we return 409 rather than 500,
    so the client gets a meaningful error message instead of a traceback.
    """
    folder_repo = FolderRepository(conn)
    file_repo = FileRepository(conn)

    if folder_repo.get_by_path(body.path):
        raise HTTPException(
            status_code=409,
            detail=f"Folder already registered: {body.path!r}",
        )

    folder_row = folder_repo.create(body.path)
    scan_summary = scan_folder(
        folder_id=folder_row["folder_id"],
        folder_path=body.path,
        file_repo=file_repo,
    )

    # Start watching AFTER the initial scan so the watcher picks up only
    # incremental changes from this point forward. If we started the watch
    # before the scan, events fired during scanning would duplicate upserts
    # (harmless but noisy).
    watcher_service.add_watch(
        folder_id=folder_row["folder_id"],
        folder_path=body.path,
    )

    return FolderCreateResponse(
        folder=FolderResponse(**dict(folder_row)),
        **scan_summary,
    )


@router.delete("/{folder_id}", status_code=204)
def remove_folder(folder_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """
    Remove a folder and all its associated files from the database.
    SQLite's ON DELETE CASCADE handles the files rows automatically.
    FAISS cleanup will be wired here in Iteration 4 — noted, not yet needed.
    Returns 204 No Content on success, 404 if the folder doesn't exist.
    """
    repo = FolderRepository(conn)
    if not repo.get(folder_id):
        raise HTTPException(status_code=404, detail=f"Folder {folder_id} not found.")
    # Stop watching BEFORE deleting the DB row — the handle is still in
    # the watcher's internal dict at this point.
    watcher_service.remove_watch(folder_id)
    repo.delete(folder_id)
    # 204 → FastAPI returns no body automatically when return value is None.
