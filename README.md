# Memoria — Iteration 1 Skeleton

Scope: FastAPI app + SQLite wiring + `/health`. No folder scanning, file
watching, embeddings, FAISS, or RAG yet — those are later iterations.

## Run it

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Then check http://127.0.0.1:8000/health — you should get:
```json
{"status": "ok", "db_connected": true, "version": "0.1.0"}
```

This confirms two things at once: the FastAPI app boots, and it can
create/write to the SQLite database (data/memoria.db, created on
first run) via the same connection pattern every later feature will use.

## What's here

- `main.py` — app composition root. Registers routers, runs `init_db()` on startup.
- `config/settings.py` — single source of truth for paths/config.
- `db/database.py` — SQLite connection handling (WAL mode) + schema (`folders`, `files`, `chunks`).
- `api/health.py`, `schemas/health.py` — the one working endpoint.

## What's deliberately NOT here yet

`services/`, `vector/`, `processors/` exist as empty directories matching
the target module layout, but have no code — they get filled in during
Iterations 2–6 (folder access, file watching, document processing,
embeddings/FAISS, RAG) per the project's own priority order.

## Schema notes

`chunks` already has `faiss_id`, `embedding_model`, `embedding_dim`
columns even though nothing populates them yet. This is intentional:
when the model-comparison experiment (swapping MiniLM for BGE-small,
say) happens later, `embedding_model`/`embedding_dim` let the app
detect a stale embedding instead of silently mixing incompatible
vectors in FAISS.
