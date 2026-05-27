from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EditorProjectUpsert(BaseModel):
    """Client → server payload for PUT /api/editor-projects.

    The state_json is intentionally typed as ``dict`` (not a strict shape) —
    the editor state schema evolves on the client and we don't want a
    rolling Pydantic migration on every reducer change. Use schema_version
    to gate hydration on the read side.
    """

    video_id: str = Field(..., max_length=64)
    title: str = Field(default="Untitled", max_length=200)
    state_json: dict[str, Any]
    schema_version: int = Field(default=1, ge=1, le=1000)


class EditorProjectResponse(BaseModel):
    id: UUID
    video_id: str
    title: str
    state_json: dict[str, Any]
    schema_version: int
    created_at: datetime
    updated_at: datetime
