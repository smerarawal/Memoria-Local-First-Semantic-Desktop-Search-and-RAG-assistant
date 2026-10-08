"""
API router for file inspection.

Endpoints:
  GET /files             — list all known files (optionally filtered by folder)
  GET /files/{id}        — get metadata for a single file

This router is read-only. Files are created/updated by the scanner (via the
folders router) and eventually by the file watcher (Iteration 3). The reason
to keep file reads here rather than folding them into the folders router is
separation of concerns: folder management is about folder lifecycle, this is
about inspecting file metadata — they're different resources even if related.

Query param `folder_id` on GET /files:
  Optional. When provided, only files belonging to that folder are returned.
  Useful for the UI's "show me what's in this folder" view without needing
  a nested route (/folders/{id}/files) that would couple the two routers.
"""

import os
import subprocess
import sys
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from db.database import get_db
from db.repositories import FileRepository
from schemas.files import FileResponse


class OpenFileRequest(BaseModel):
    path: Optional[str] = None
    file_id: Optional[int] = None

router = APIRouter(prefix="/files", tags=["files"])


@router.get("", response_model=list[FileResponse])
def list_files(
    folder_id: Optional[int] = Query(default=None, description="Filter by folder ID"),
    conn: sqlite3.Connection = Depends(get_db),
):
    """
    Return all known files, optionally filtered to a single folder.
    Files with status='deleted' are included — the UI can choose to hide
    them or show them with a strikethrough; that's a UI decision not a
    backend one.
    """
    repo = FileRepository(conn)
    rows = repo.list_all(folder_id=folder_id)
    return [dict(r) for r in rows]


@router.get("/{file_id}", response_model=FileResponse)
def get_file(file_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Return metadata for a single file. 404 if not found."""
    repo = FileRepository(conn)
    row = repo.get(file_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"File {file_id} not found.")
    return dict(row)


@router.post("/open")
def open_file_desktop(body: OpenFileRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Open the file in the operating system's default application."""
    file_path = body.path
    if not file_path and body.file_id is not None:
        repo = FileRepository(conn)
        row = repo.get(body.file_id)
        if row:
            file_path = row["path"]

    if not file_path:
        raise HTTPException(status_code=400, detail="Missing file path or id.")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found on disk: {file_path}")

    try:
        norm_path = os.path.normpath(file_path)
        if sys.platform == "win32":
            os.startfile(norm_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", norm_path], check=True)
        else:
            subprocess.run(["xdg-open", norm_path], check=True)
        return {"status": "ok", "opened": norm_path}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not open file: {exc}")


@router.post("/{file_id}/open")
def open_file_by_id(file_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Open file by file_id in the OS."""
    return open_file_desktop(OpenFileRequest(file_id=file_id), conn=conn)


@router.post("/reveal")
def reveal_file_desktop(body: OpenFileRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Reveal the file in File Explorer / Finder."""
    file_path = body.path
    if not file_path and body.file_id is not None:
        repo = FileRepository(conn)
        row = repo.get(body.file_id)
        if row:
            file_path = row["path"]

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk.")

    try:
        norm_path = os.path.normpath(file_path)
        if sys.platform == "win32":
            subprocess.run(["explorer", f"/select,{norm_path}"], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", norm_path], check=True)
        else:
            subprocess.run(["xdg-open", os.path.dirname(norm_path)], check=True)
        return {"status": "ok", "revealed": norm_path}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not reveal file: {exc}")
