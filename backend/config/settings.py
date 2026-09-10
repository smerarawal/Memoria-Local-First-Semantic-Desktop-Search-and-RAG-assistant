"""
Central configuration for Memoria backend.

Why this file exists:
Every other module (db, api, services) should import settings from here
instead of hardcoding paths or values. When we add folder indexing,
FAISS, and the LLM in later iterations, their config lives here too —
one place to look, one place to change.
"""

from pathlib import Path

# Root of the whole Memoria application (not just backend/)
# Used to derive default data locations.
APP_ROOT = Path(__file__).resolve().parent.parent.parent

# Where Memoria stores its own data: the SQLite DB, the FAISS index file,
# cached extracted text, etc. Kept separate from user files — Memoria
# never writes into folders the user asked it to index.
DATA_DIR = APP_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SQLITE_PATH = DATA_DIR / "memoria.db"
FAISS_INDEX_PATH = DATA_DIR / "memoria.faiss"

# API metadata
API_TITLE = "Memoria API"
API_VERSION = "0.1.0"
