"""
Pydantic schema for the index/watcher status response.

Kept separate from folders.py / files.py because index status is a
cross-cutting concern — it aggregates data from the watcher service (which
folders are actively monitored) AND from SQLite (file counts by status).
Mixing it into the folder schema would blur that boundary.
"""

from typing import Optional
from pydantic import BaseModel


class IndexStatusResponse(BaseModel):
    """
    Returned by GET /index/status.

    Fields:
      watcher_running     — True if the background Observer thread is alive.
      watched_folders     — How many folder paths are actively monitored.
      watched_folder_ids  — The folder_id values being watched (for debugging).
      total_files         — All file rows in the DB (any status).
      pending_files       — Files discovered but not yet text-extracted/embedded.
      indexed_files       — Files that have been fully processed.
      failed_files        — Files where processing encountered an error.
      deleted_files       — Files marked deleted by the watcher.
    """

    watcher_running: bool
    watched_folders: int
    watched_folder_ids: list[int]
    total_files: int
    pending_files: int
    indexed_files: int
    failed_files: int
    deleted_files: int
