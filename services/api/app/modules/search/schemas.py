from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.modules.ingest.schemas import SourceType


# ---------------------------------------------------------------------------
# Reusable constraints
# ---------------------------------------------------------------------------
_MAX_TAG_LIST_SIZE = 50
_MAX_TAG_ITEM_LEN = 64


def _clean_tag_list(values: list[str] | None) -> list[str]:
    """Strip whitespace, drop empty strings, and enforce per-item max length."""
    if values is None:
        return []
    cleaned: list[str] = []
    for v in values:
        v = v.strip()
        if v:
            cleaned.append(v[:_MAX_TAG_ITEM_LEN])
    return cleaned


class SearchFilters(BaseModel):
    date_from: datetime | None = None
    date_to: datetime | None = None
    content_types: list[str] = Field(default_factory=lambda: ["video"])
    source_types: list[SourceType] | None = None
    library_ids: list[UUID] | None = None
    person_cluster_ids: list[str] | None = None
    person_cluster_ids_not_in: list[str] | None = None

    # Tag-based scene filters (additive — empty list = no filter)
    keyword_tags_in: list[str] = Field(default_factory=list, max_length=_MAX_TAG_LIST_SIZE)
    keyword_tags_not_in: list[str] = Field(default_factory=list, max_length=_MAX_TAG_LIST_SIZE)
    product_tags_in: list[str] = Field(default_factory=list, max_length=_MAX_TAG_LIST_SIZE)
    product_tags_not_in: list[str] = Field(default_factory=list, max_length=_MAX_TAG_LIST_SIZE)
    product_entities_in: list[str] = Field(default_factory=list, max_length=_MAX_TAG_LIST_SIZE)
    product_entities_not_in: list[str] = Field(default_factory=list, max_length=_MAX_TAG_LIST_SIZE)
    ai_tags_in: list[str] = Field(default_factory=list, max_length=_MAX_TAG_LIST_SIZE)
    ai_tags_not_in: list[str] = Field(default_factory=list, max_length=_MAX_TAG_LIST_SIZE)

    @field_validator(
        "keyword_tags_in",
        "keyword_tags_not_in",
        "product_tags_in",
        "product_tags_not_in",
        "product_entities_in",
        "product_entities_not_in",
        "ai_tags_in",
        "ai_tags_not_in",
        mode="before",
    )
    @classmethod
    def _clean_tags(cls, v: list[str] | None) -> list[str]:
        return _clean_tag_list(v)


class SearchRequest(BaseModel):
    q: str = Field(default="", max_length=1000)
    alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    search_mode: Literal["metadata", "lexical", "semantic"] = Field(
        default="lexical",
        description=(
            "Search strategy. 'metadata'=file properties (title, source), "
            "'lexical'=exact words in content (transcript/OCR/caption), "
            "'semantic'=meaning-based vector search. "
            "When search_mode is set, it takes precedence over alpha."
        ),
    )
    filters: SearchFilters = Field(default_factory=lambda: SearchFilters())
    include_ocr: bool | None = Field(
        default=None,
        description="Per-request OCR toggle. None=server default, True=include, False=exclude",
    )
    group_by: Literal["video", "scene"] = Field(
        default="scene",
        description="Result granularity. 'scene' returns individual scenes, 'video' groups by video.",
    )
    color_hex: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Hex color for color-based search (e.g. '#ff0000'). Activates color kNN signal.",
    )
    color_family: str | None = Field(
        default=None,
        description=(
            "Broad color family name (e.g. 'pink', 'blue'). "
            "Activates dominant-color-family search. Takes precedence over color_hex."
        ),
    )
    page_size: int | None = Field(
        default=None,
        ge=1,
        le=120,
        description=(
            "Override server default page size (post-diversification result count). "
            "None=use settings.search_page_size. Clamped to settings.search_page_size_max."
        ),
    )
    max_per_video: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description=(
            "Override per-video diversification cap. None=use settings.search_max_scenes_per_video. "
            "Raise this alongside page_size to avoid underfill on small corpora."
        ),
    )
    offset: int = Field(
        default=0,
        ge=0,
        le=10_000,
        description=(
            "Pagination offset. Honored in metadata mode only — lexical/"
            "semantic diversification is stateful and can't be sliced with "
            "offset, so those modes log a warning and ignore any non-zero "
            "value. Page N (1-indexed) is offset=(N-1)*page_size. Upper "
            "bound mirrors OpenSearch's default index.max_result_window; "
            "raising requires bumping the index setting."
        ),
    )


class DebugInfo(BaseModel):
    lexical_rank: int | None = None
    lexical_score: float | None = None
    vector_rank: int | None = None
    vector_score: float | None = None
    visual_rank: int | None = None
    visual_score: float | None = None
    color_rank: int | None = None
    color_score: float | None = None
    lexical_contribution: float = 0.0
    vector_contribution: float = 0.0
    visual_contribution: float = 0.0
    color_contribution: float = 0.0
    ocr_contribution: float = 0.0
    reranker_score: float | None = None
    fused_score: float
    quality_factor: float = 1.0
    adjusted_score: float
    diversification_penalty: bool = False


class SegmentResult(BaseModel):
    segment_id: str
    video_id: str
    video_title: str | None = None
    library_id: UUID
    library_name: str
    start_ms: int
    end_ms: int
    snippet: str
    thumbnail_url: str | None
    source_type: SourceType
    web_view_link: str | None = None
    required_drive_nickname: str | None = None
    capture_time: datetime | None = None
    people_cluster_ids: list[str] = Field(default_factory=list)
    keyframe_timestamp_ms: int = 0
    debug: DebugInfo


class FacetItem(BaseModel):
    value: str
    count: int
    label: str | None = None


class Facets(BaseModel):
    libraries: list[FacetItem] = Field(default_factory=list)
    source_types: list[FacetItem] = Field(default_factory=list)
    people_cluster_ids: list[FacetItem] = Field(default_factory=list)
    content_types: list[FacetItem] = Field(default_factory=list)


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
    video_title: str | None = None
    library_id: UUID
    library_name: str
    start_ms: int
    end_ms: int
    snippet: str
    ocr_snippet: str = ""
    scene_caption: str = ""
    thumbnail_url: str | None
    source_type: SourceType
    web_view_link: str | None = None
    required_drive_nickname: str | None = None
    capture_time: datetime | None = None
    people_cluster_ids: list[str] = Field(default_factory=list)
    speech_segment_count: int = 0
    ocr_char_count: int = 0
    speaker_transcript: str = ""
    speaker_count: int = 0
    keyword_tags: list[str] = Field(default_factory=list)
    product_tags: list[str] = Field(default_factory=list)
    product_entities: list[str] = Field(default_factory=list)
    ai_tags: list[str] = Field(default_factory=list)
    keyframe_timestamp_ms: int = 0
    content_type: str = "video"
    image_width: int | None = None
    image_height: int | None = None
    image_orientation: str | None = None
    dominant_colors: list[str] = Field(default_factory=list)
    debug: DebugInfo


class SceneSearchResponse(BaseModel):
    results: list[SceneResult]
    total_candidates: int
    facets: Facets
    query: str
    alpha: float
    result_type: Literal["scene"] = "scene"
    # Id of the search_events row this response was logged under, so the client
    # can attach interaction events (impression/click) back to this search.
    # None when analytics is disabled or the event write failed.
    search_event_id: int | None = None


# ---------------------------------------------------------------------------
# Video-grouped search models
# ---------------------------------------------------------------------------


class VideoResult(BaseModel):
    video_id: str
    video_title: str | None = None
    library_id: UUID
    library_name: str
    source_type: SourceType
    web_view_link: str | None = None
    matching_scene_count: int
    best_scene: SceneResult
    score: float


class VideoSearchResponse(BaseModel):
    results: list[VideoResult]
    total_candidates: int
    facets: Facets
    query: str
    alpha: float
    result_type: Literal["video"] = "video"
    # See SceneSearchResponse.search_event_id.
    search_event_id: int | None = None


# ---------------------------------------------------------------------------
# Search-result interaction logging (impression / click / play_*)
# ---------------------------------------------------------------------------

_MAX_INTERACTION_BATCH = 200


class InteractionItem(BaseModel):
    event_type: Literal["impression", "click", "play_start", "play_complete"]
    # Bounded so a client cannot store arbitrarily large strings in TEXT
    # columns (scene_id is e.g. "{video_id}_scene_NNN", well under 200).
    scene_id: str | None = Field(default=None, max_length=200)
    video_id: str | None = Field(default=None, max_length=200)
    # 0-indexed position within the search results. Bounded to keep values
    # inside the INTEGER column (an out-of-range int would error at INSERT).
    result_position: int | None = Field(default=None, ge=0, le=10_000)
    # "video" | "image": which search surface the result came from. Closed
    # set (Literal) instead of free TEXT, matching the backend.
    content_type: Literal["video", "image"] | None = None
    # Dwell time; 24h sanity ceiling, also keeps it inside INTEGER.
    dwell_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class SearchInteractionRequest(BaseModel):
    # Links the interactions back to the search they came from (from
    # SceneSearchResponse.search_event_id). None when unavailable.
    #
    # Cross-org spoofing (a client posting another org's event id) is handled at
    # the analytics-join layer, not by a server-side ownership check: that check
    # would be a cross-partition scan on search_events (no id-alone index; the
    # client never sends created_at, the partition key). Instead, each
    # interaction row stores the AUTHENTICATED org_id, so any downstream join
    # keyed on (search_event_id, org_id) drops an event id that belongs to a
    # different org. ge=1 just rejects obviously-invalid ids (<=0) early.
    search_event_id: int | None = Field(default=None, ge=1)
    # Batched so a single search-result render can post all impressions at once.
    results: list[InteractionItem] = Field(default_factory=list, max_length=_MAX_INTERACTION_BATCH)
