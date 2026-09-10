import sqlite3

from fastapi import APIRouter, Depends

from config.settings import API_VERSION
from db.database import get_db
from schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check(conn: sqlite3.Connection = Depends(get_db)):
    """
    Returns app status and confirms the DB connection actually works —
    not just that the process is alive. This is the endpoint you hit
    to sanity-check the skeleton before building anything on top of it.
    """
    try:
        conn.execute("SELECT 1")
        db_connected = True
    except sqlite3.Error:
        db_connected = False

    return HealthResponse(
        status="ok" if db_connected else "degraded",
        db_connected=db_connected,
        version=API_VERSION,
    )
