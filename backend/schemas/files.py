"""
Pydantic schemas for file-related API endpoints.

FileResponse mirrors the `files` table columns that are safe to expose over
the API. We don't expose content_hash to the client — it's an internal
change-detection key, not meaningful UI data. If we need it for debugging
later, we can add a separate admin endpoint.
"""

from typing import Optional

from pydantic import BaseModel


class FileResponse(BaseModel):
    file_id: int
    folder_id: int
    filename: str
    path: str
    extension: str
    size_bytes: int
    created_at: Optional[str] = None
    modified_at: Optional[str] = None
    indexed_at: Optional[str] = None
    status: str

    model_config = {"from_attributes": True}
