from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    date_from: datetime | None = None
    date_to: datetime | None = None
    source_types: list[Literal["gdrive", "removable_disk"]] | None = None
    library_ids: list[UUID] | None = None
    person_cluster_ids: list[str] | None = None


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=1000)
    alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class DebugInfo(BaseModel):
    lexical_rank: int | None = None
    lexical_score: float | None = None
    vector_rank: int | None = None
    vector_score: float | None = None
    lexical_contribution: float = 0.0
    vector_contribution: float = 0.0
    fused_score: float
    quality_factor: float = 1.0
    adjusted_score: float
    diversification_penalty: bool = False


class SegmentResult(BaseModel):
    segment_id: str
    video_id: str
    library_id: UUID
    library_name: str
    start_ms: int
    end_ms: int
    snippet: str
    thumbnail_url: str | None
    source_type: Literal["gdrive", "removable_disk"]
    required_drive_nickname: str | None = None
    capture_time: datetime | None = None
    people_cluster_ids: list[str] = Field(default_factory=list)
    debug: DebugInfo


class FacetItem(BaseModel):
    value: str
    count: int
    label: str | None = None


class Facets(BaseModel):
    libraries: list[FacetItem] = Field(default_factory=list)
    source_types: list[FacetItem] = Field(default_factory=list)
    people_cluster_ids: list[FacetItem] = Field(default_factory=list)


class SearchResponse(BaseModel):
    results: list[SegmentResult]
    total_candidates: int
    facets: Facets
    query: str
    alpha: float
    result_type: Literal["segment"] = "segment"


# ---------------------------------------------------------------------------
# Scene search models
# ---------------------------------------------------------------------------


class SceneResult(BaseModel):
    """A single scene search result.

    Structurally parallel to SegmentResult but uses scene_id instead of
    segment_id and carries scene-specific metadata (speech_segment_count).
    """
    scene_id: str
    video_id: str
    library_id: UUID
    library_name: str
    start_ms: int
    end_ms: int
    snippet: str
    thumbnail_url: str | None
    source_type: Literal["gdrive", "removable_disk"]
    required_drive_nickname: str | None = None
    capture_time: datetime | None = None
    people_cluster_ids: list[str] = Field(default_factory=list)
    speech_segment_count: int = 0
    debug: DebugInfo


class SceneSearchResponse(BaseModel):
    results: list[SceneResult]
    total_candidates: int
    facets: Facets
    query: str
    alpha: float
    result_type: Literal["scene"] = "scene"
