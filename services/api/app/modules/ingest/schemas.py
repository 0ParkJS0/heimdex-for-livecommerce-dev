from pydantic import BaseModel, Field

from heimdex_media_contracts.ingest import (
    IngestSceneDocument,
    IngestScenesRequest,
    SourceType,
)

__all__ = [
    "IngestSceneDocument",
    "IngestScenesRequest",
    "IngestScenesResponse",
    "SourceType",
]


class IngestScenesResponse(BaseModel):
    indexed_count: int = Field(...)
    video_id: str = Field(...)
    skipped_count: int = Field(default=0)
