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
    "EnrichSceneUpdate",
    "EnrichScenesRequest",
    "EnrichScenesResponse",
    "SourceType",
    "TranscriptWord",
]


class TranscriptWord(BaseModel):
    """One word-level timestamp from a Whisper-style STT pass.

    Populated by ``drive-stt-worker`` (cross-repo) at enrichment time.
    The timestamps are absolute milliseconds relative to the source
    video, not relative to the scene window — the scene-aware filter
    happens at read time so a single Whisper pass over the full audio
    can fan out to every overlapping scene without re-running.
    """

    word: str = Field(..., min_length=1)
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)


class IngestScenesResponse(BaseModel):
    indexed_count: int = Field(...)
    video_id: str = Field(...)
    skipped_count: int = Field(default=0)


class EnrichSceneUpdate(BaseModel):
    """Partial scene update for enrichment workers.

    Only fields explicitly set (not None) will be merged into the existing
    OpenSearch document. This prevents enrichment workers from overwriting
    each other's data.
    """

    scene_id: str = Field(...)
    transcript_raw: str | None = Field(default=None)
    speech_segment_count: int | None = Field(default=None)
    speaker_transcript: str | None = Field(default=None)
    speaker_count: int | None = Field(default=None)
    # Do not set max_length here. The ingest service applies
    # heimdex_media_contracts.ocr.gate_ocr_text(), whose G4 rule clamps
    # overlong OCR to 10,000 chars. Rejecting before that boundary would
    # turn a contract clamp into a 422 and break legacy/backfill workers.
    ocr_text_raw: str | None = Field(default=None)
    ocr_char_count: int | None = Field(default=None)
    scene_caption: str | None = Field(default=None)
    keyword_tags: list[str] | None = Field(default=None)
    product_tags: list[str] | None = Field(default=None)
    product_entities: list[str] | None = Field(default=None)
    ai_tags: list[str] | None = Field(default=None)
    people_cluster_ids: list[str] | None = Field(default=None)
    visual_embedding: list[float] | None = Field(default=None)
    color_embedding: list[float] | None = Field(default=None)
    dominant_colors: list[str] | None = Field(default=None)
    # Word-level transcript from Whisper (or any STT pass that returns
    # word-grain timestamps). Filtered to words whose timestamp window
    # overlaps the scene's [start_ms, end_ms]; downstream consumers can
    # rely on each entry's start/end being scene-relative-ish but still
    # absolute. ``drive-stt-worker`` populates this; older workers that
    # don't ship word data simply omit the field and existing scenes
    # stay backward-compatible.
    transcript_words: list[TranscriptWord] | None = Field(default=None)


class EnrichScenesRequest(BaseModel):
    """Request to merge enrichment data into existing scenes."""

    video_id: str = Field(..., min_length=1)
    scenes: list[EnrichSceneUpdate] = Field(...)


class EnrichScenesResponse(BaseModel):
    updated_count: int = Field(...)
    video_id: str = Field(...)
    skipped_count: int = Field(default=0)
