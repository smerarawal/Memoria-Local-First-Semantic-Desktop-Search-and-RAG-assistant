"""
Memoria backend entrypoint.

Iteration 4 adds: document processing pipeline (extraction + chunking +
embeddings + FAISS) + GET /search + POST /index + POST /index/rebuild.
main.py stays a thin composition root — lifecycle + router registration.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import threading
from contextlib import asynccontextmanager

from api import files, folders, health, indexing, search
from config.settings import API_TITLE, API_VERSION
from db.database import init_db
from services.document_service import start_background_worker, stop_background_worker
from services.embedding_service import embedding_service
from services.file_watcher_service import watcher_service

@asynccontextmanager
async def lifespan(app_: object):
    """
    FastAPI lifespan context manager — replaces the deprecated on_event
    decorator. Code before `yield` runs on startup; code after runs on shutdown.

    Startup order matters:
      1. init_db() first — creates tables so the watcher can write to them.
      2. watcher_service.start() second — reads the folders table to
         re-schedule watches from previous sessions.

    Shutdown:
      watcher_service.stop() joins the Observer thread cleanly so the process
      exits without a dangling daemon thread warning.
    """
    init_db()
    # Load embedding model in a background thread so we don't block
    # uvicorn's startup timeout if the model download takes a long time.
    threading.Thread(target=embedding_service.load, daemon=True).start()
    
    watcher_service.start()
    start_background_worker()
    yield
    stop_background_worker()
    watcher_service.stop()


app = FastAPI(title=API_TITLE, version=API_VERSION, lifespan=lifespan)

# Permissive CORS for local dev only — the React frontend runs on a
# different port (5173/3000) than the backend (8000) during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(health.router)
app.include_router(folders.router)
app.include_router(files.router)
app.include_router(indexing.router)
app.include_router(search.router)
