"""Domain types for the full-STT product explainer path.

No imports from storyboard/, chunk_scorer, mention_extractor, segment_assembler,
or any other track_stt submodule — this module is the root of the full_stt
dependency graph.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FullSttScene:
    """One OS scene, flattened for the explainer picker.

    text priority: transcript_raw when non-empty, speaker_transcript otherwise.
    No BM25 or chunk scores — the LLM derives relevance from content.
    """

    scene_id: str
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class FullSttSegment:
    """One LLM-selected segment in the output plan."""

    scene_id: str
    source_start_ms: int
    source_end_ms: int
    rationale: str = ""

    @property
    def duration_ms(self) -> int:
        return self.source_end_ms - self.source_start_ms


@dataclass(frozen=True)
class FullSttClipPlan:
    """Output of FullSttExplainerPicker.

    Segments are chronological, non-overlapping. Falls back to a positional
    plan when the LLM fails; ``fallback_used=True`` in that case.
    """

    segments: list[FullSttSegment]
    total_duration_ms: int
    global_rationale: str = ""
    fallback_used: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.segments
