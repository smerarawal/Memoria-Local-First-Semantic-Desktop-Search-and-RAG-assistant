"""
File watcher service — real-time folder monitoring using watchdog.

This module owns a single WatcherService instance (module-level singleton).
FastAPI startup/shutdown lifecycle starts and stops the underlying watchdog
Observer. The folders router calls add_watch() / remove_watch() whenever
folders are registered or deleted.

Threading model
---------------
watchdog's Observer runs its own daemon thread. Event handlers (on_created,
on_modified, on_deleted, on_moved) are called from that thread, NOT from a
FastAPI worker thread. This has two important consequences:

  1. We CANNOT use FastAPI's Depends(get_db) here. Instead every handler
     opens its own SQLite connection via db_session() and closes it when done.
     WAL mode (set in database.py) ensures these background writes don't block
     concurrent API reads.

  2. The _watches dict is accessed from both the main thread (add_watch /
     remove_watch) and the Observer thread. We protect it with a threading.Lock.

Debouncing
----------
Many editors (VS Code, LibreOffice, Word) emit multiple MODIFIED events in
rapid succession when saving a file: a truncate, then one or more writes.
Without debouncing, each event triggers a hash + DB write. We keep a simple
{path: last_seen_time} dict and ignore any event that arrives within
DEBOUNCE_SECONDS of the previous one for the same path.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from db.database import db_session
from db.repositories import FileRepository, FolderRepository
from processors.file_utils import compute_content_hash, is_supported

logger = logging.getLogger(__name__)

# Minimum seconds between processing two events for the same file path.
# 1 second is conservative; 0.5 s works for most editors but 1 s is safer
# for network drives or slow spinning disks.
DEBOUNCE_SECONDS: float = 1.0


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class MemoriaEventHandler(FileSystemEventHandler):
    """
    watchdog event handler bound to a single watched folder.

    Each registered folder gets its own handler instance so we can store
    the folder_id alongside the handler without a DB lookup on every event.
    """

    def __init__(self, folder_id: int, folder_path: str):
        super().__init__()
        self.folder_id = folder_id
        self.folder_path = folder_path
        # Debounce state: maps absolute path string → POSIX timestamp of
        # last processed event. Accessed only from the Observer thread, so
        # no lock needed here (single writer, no concurrent readers).
        self._last_event: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _debounce(self, path: str) -> bool:
        """
        Return True if this event should be processed (i.e. it is NOT a
        duplicate within the debounce window).
        Updates the last-seen timestamp as a side effect.
        """
        now = time.monotonic()
        last = self._last_event.get(path, 0.0)
        if (now - last) < DEBOUNCE_SECONDS:
            return False
        self._last_event[path] = now
        return True

    def _handle_create_or_modify(self, path_str: str) -> None:
        """
        Shared logic for CREATE and MODIFY events.
        Opens its own DB connection — this runs on the Observer thread,
        not a FastAPI worker thread.
        """
        path = Path(path_str)

        if not is_supported(path):
            return
        if not self._debounce(path_str):
            logger.debug("Debounced event for %s", path_str)
            return

        try:
            stat = path.stat()
            content_hash = compute_content_hash(path)
        except OSError as exc:
            # File disappeared between the event and our stat (race condition
            # during rapid save-delete cycles). Not an error worth logging loudly.
            logger.debug("Could not stat %s: %s", path_str, exc)
            return

        with db_session() as conn:
            file_repo = FileRepository(conn)
            _row, status = file_repo.upsert(
                folder_id=self.folder_id,
                filename=path.name,
                path=path_str,
                extension=path.suffix.lower(),
                size_bytes=stat.st_size,
                created_at=_iso(stat.st_ctime),
                modified_at=_iso(stat.st_mtime),
                content_hash=content_hash,
            )
        logger.info("[watcher] %s → %s (%s)", status.upper(), path.name, path_str)

    def _handle_delete(self, path_str: str) -> None:
        """
        Mark a file as deleted in SQLite.

        We use a soft-delete (status='deleted') rather than removing the row
        immediately. This keeps the metadata available so the UI can show
        "this file was removed" rather than silently disappearing. Hard
        deletion (removing the row + FAISS vectors) is the job of a future
        cleanup step added in Iteration 4.
        """
        path = Path(path_str)
        if not is_supported(path):
            return

        with db_session() as conn:
            file_repo = FileRepository(conn)
            existing = file_repo.get_by_path(path_str)
            if existing:
                file_repo.mark_deleted(existing["file_id"])
                logger.info("[watcher] DELETED → %s", path_str)

    # ------------------------------------------------------------------
    # watchdog event callbacks
    # ------------------------------------------------------------------

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        self._handle_create_or_modify(event.src_path)

    def on_modified(self, event: FileModifiedEvent) -> None:
        if event.is_directory:
            return
        self._handle_create_or_modify(event.src_path)

    def on_deleted(self, event: FileDeletedEvent) -> None:
        if event.is_directory:
            return
        self._handle_delete(event.src_path)

    def on_moved(self, event: FileMovedEvent) -> None:
        """
        Treat a MOVE/RENAME as DELETE-old + CREATE-new.

        This keeps each handler simple. Edge cases:
          - Old path was indexed, new path is in the same watched folder
            → old row marked deleted, new row upserted (new file_id).
          - Old path was not indexed (unsupported extension) → no-op for delete.
          - New path has unsupported extension → no-op for create.
          - New path is outside any watched folder → only the delete fires here;
            the create won't be caught because the new path isn't watched.
            That's correct: Memoria only indexes what the user asked it to watch.
        """
        if event.is_directory:
            return
        self._handle_delete(event.src_path)
        self._handle_create_or_modify(event.dest_path)


class WatcherService:
    """
    Singleton wrapper around watchdog's Observer.

    Lifecycle:
      start()      — called on FastAPI startup, boots the Observer thread and
                     schedules watches for all enabled folders already in the DB.
      stop()       — called on FastAPI shutdown, cleanly stops the Observer.
      add_watch()  — called by the folders router after a folder is inserted.
      remove_watch()— called by the folders router before a folder is deleted.
      status()     — returns a snapshot dict for the /index/status endpoint.
    """

    def __init__(self) -> None:
        self._observer: Optional[Observer] = None
        # Maps folder_id → watchdog WatchHandle (the object returned by
        # observer.schedule()). We need the handle to call unschedule() later.
        self._watches: dict[int, object] = {}
        self._lock = threading.Lock()
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Boot the Observer and schedule watches for every enabled folder
        currently in the database. Called once on FastAPI startup.
        """
        if self._running:
            logger.warning("WatcherService.start() called but already running")
            return

        self._observer = Observer()
        self._observer.start()
        self._running = True
        logger.info("[watcher] Observer started")

        # Re-schedule all folders that were registered in a previous session.
        with db_session() as conn:
            folder_repo = FolderRepository(conn)
            for row in folder_repo.list_all():
                if row["enabled"]:
                    folder_path = row["path"]
                    if not Path(folder_path).is_dir():
                        # The folder was deleted externally between sessions.
                        # Skip silently — the user will notice it's gone and
                        # can remove it via DELETE /folders/{id}.
                        logger.warning(
                            "[watcher] Skipping stale folder (path no longer exists): %s",
                            folder_path,
                        )
                        continue
                    self.add_watch(row["folder_id"], folder_path)

    def stop(self) -> None:
        """Cleanly shut down the Observer thread. Called on FastAPI shutdown."""
        if not self._running or self._observer is None:
            return
        self._observer.stop()
        self._observer.join()
        self._running = False
        # Clear the handles dict: they belong to this Observer instance and
        # are invalid after it stops. If start() is called again (resume),
        # it will create a fresh Observer and fresh handles via add_watch().
        with self._lock:
            self._watches.clear()
        self._observer = None
        logger.info("[watcher] Observer stopped")

    # ------------------------------------------------------------------
    # Watch management (called from the folders API router)
    # ------------------------------------------------------------------

    def add_watch(self, folder_id: int, folder_path: str) -> None:
        """
        Tell the Observer to start watching `folder_path`.
        Safe to call even if the observer hasn't started yet (no-op then);
        start() will pick up all DB folders anyway.
        """
        if not self._running or self._observer is None:
            return

        with self._lock:
            if folder_id in self._watches:
                logger.debug("Watch already active for folder_id=%d", folder_id)
                return
            if not Path(folder_path).is_dir():
                logger.warning(
                    "[watcher] Cannot watch folder_id=%d: path does not exist: %s",
                    folder_id, folder_path,
                )
                return
            handler = MemoriaEventHandler(
                folder_id=folder_id, folder_path=folder_path
            )
            try:
                watch_handle = self._observer.schedule(
                    handler, folder_path, recursive=True
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[watcher] Failed to schedule watch for %s: %s", folder_path, exc
                )
                return
            self._watches[folder_id] = watch_handle
            logger.info(
                "[watcher] Now watching folder_id=%d  path=%s", folder_id, folder_path
            )

    def remove_watch(self, folder_id: int) -> None:
        """
        Stop watching the folder identified by folder_id.
        Called from the folders router BEFORE the DB row is deleted,
        so we can still look up the path if needed (we don't need it here,
        but the ordering is a good habit).
        """
        if not self._running or self._observer is None:
            return

        with self._lock:
            handle = self._watches.pop(folder_id, None)
            if handle is not None:
                try:
                    self._observer.unschedule(handle)
                except KeyError:
                    # Handle is stale (can happen if the Observer was restarted
                    # e.g. via pause/resume and the handle wasn't refreshed).
                    logger.warning(
                        "[watcher] Stale handle for folder_id=%d (already unscheduled)",
                        folder_id,
                    )
                logger.info(
                    "[watcher] Stopped watching folder_id=%d", folder_id
                )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """
        Return a snapshot of the watcher's current state.
        Used by GET /index/status — gives the UI enough information to
        show "Monitoring: ON • 3 folders watched • 42 files indexed".
        """
        with self._lock:
            watched_count = len(self._watches)
            watched_folder_ids = list(self._watches.keys())

        return {
            "running": self._running,
            "watched_folders": watched_count,
            "watched_folder_ids": watched_folder_ids,
        }


# Module-level singleton — imported by main.py (lifecycle) and by the
# folders router (add_watch / remove_watch).
watcher_service = WatcherService()
