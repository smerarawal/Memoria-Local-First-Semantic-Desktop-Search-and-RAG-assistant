"""
Pydantic schemas for folder-related API endpoints.

Three models:
  FolderCreateRequest  — what the client sends when adding a folder
  FolderResponse       — a folder row as returned by the API
  FolderCreateResponse — the full response to POST /folders, which includes
                         both the folder row and the scan summary counts

Why separate Request / Response models instead of one model:
  The client should never be able to set folder_id or created_at — those are
  server-generated. Separate models make that boundary explicit and let Pydantic
  validate the inbound payload without polluting it with output-only fields.
"""

from pydantic import BaseModel, field_validator
import os


class FolderCreateRequest(BaseModel):
    path: str

    @field_validator("path")
    @classmethod
    def path_must_exist(cls, v: str) -> str:
        """
        Reject requests for paths that don't exist on the local filesystem.
        Fail fast here so we never write a folder row for a path that can't
        be scanned. The error surfaces as a 422 Unprocessable Entity, which
        is the correct HTTP status for a validation failure.
        """
        if not os.path.isdir(v):
            raise ValueError(f"Path does not exist or is not a directory: {v!r}")
        return os.path.abspath(v)  # normalise: strip trailing slash, resolve .


class FolderResponse(BaseModel):
    folder_id: int
    path: str
    enabled: bool
    created_at: str

    model_config = {"from_attributes": True}


class FolderCreateResponse(BaseModel):
    """
    Returned by POST /folders. Bundles the new folder record with the
    scan summary so the UI can immediately show "48 files found, 3 skipped"
    without making a second request.
    """
    folder: FolderResponse
    new_files: int
    updated_files: int
    unchanged_files: int
    skipped_files: int
