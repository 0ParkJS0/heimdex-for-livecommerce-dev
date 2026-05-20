"""OpenAI structured-output schema + Pydantic validators for the full-STT picker.

Two validation layers:
1. ``_RESPONSE_JSON_SCHEMA`` — handed to OpenAI strict structured output. The
   server refuses to return malformed JSON; first line of defense.
2. ``FullSttClipResponse`` (Pydantic) — defense-in-depth on the Python side.
   Catches duplicate segment_index values. Range + timestamp + chronological +
   overlap + duration checks happen in ``picker._validate`` where the original
   scene list is available as context.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "name": "full_stt_clip_plan",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["segments", "global_rationale"],
        "properties": {
            "segments": {
                "type": "array",
                "minItems": 3,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["segment_index", "rationale"],
                    "properties": {
                        "segment_index": {
                            "type": "integer",
                            "minimum": 0,
                        },
                        "rationale": {
                            "type": "string",
                            "maxLength": 200,
                        },
                    },
                },
            },
            "global_rationale": {
                "type": "string",
                "maxLength": 500,
            },
        },
    },
}


# ── Multi-short (shared planner) schema ──────────────────────────────
# The shared planner asks for exactly N shorts in one call. The schema is
# built at call time because ``min/maxItems`` on ``shorts`` pin the count
# to the request. The per-short object adds ``differentiation_note`` (how
# this short differs from its siblings) on top of the single-short shape.

_MULTI_SHORT_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["segments", "global_rationale", "differentiation_note"],
    "properties": {
        "segments": {
            "type": "array",
            "minItems": 3,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["segment_index", "rationale"],
                "properties": {
                    "segment_index": {"type": "integer", "minimum": 0},
                    "rationale": {"type": "string", "maxLength": 200},
                },
            },
        },
        "global_rationale": {"type": "string", "maxLength": 500},
        "differentiation_note": {"type": "string", "maxLength": 200},
    },
}


def build_multi_response_schema(n: int) -> dict[str, Any]:
    """Strict structured-output schema asking for exactly ``n`` shorts.

    ``n`` pins ``shorts`` to ``minItems == maxItems == n`` so the model
    cannot under- or over-produce. ``min/maxItems`` are supported in the
    2026 strict subset (see ``feedback_openai_strict_mode_subset.md``).
    """
    return {
        "name": "full_stt_multi_clip_plan",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["shorts"],
            "properties": {
                "shorts": {
                    "type": "array",
                    "minItems": n,
                    "maxItems": n,
                    "items": _MULTI_SHORT_OBJECT_SCHEMA,
                },
            },
        },
    }


class FullSttSegmentPick(BaseModel):
    segment_index: int = Field(ge=0)
    rationale: str = Field(default="", max_length=200)

    @field_validator("rationale", mode="before")
    @classmethod
    def _coerce_rationale(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)


class FullSttClipResponse(BaseModel):
    """Top-level LLM response shape.

    The only response-intrinsic constraint checked here is segment_index
    uniqueness. All constraints that require the original scene list as context
    (range check, timestamp match, chronological order, overlap, duration
    bounds) live in ``picker._validate``.
    """

    segments: list[FullSttSegmentPick]
    global_rationale: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _check_unique_indices(self) -> FullSttClipResponse:
        _require_unique_indices(self.segments)
        return self


def _require_unique_indices(segments: list[FullSttSegmentPick]) -> None:
    indices = [s.segment_index for s in segments]
    if len(set(indices)) != len(indices):
        raise ValueError(
            f"segment_index must be unique across segments (got {indices})"
        )


class FullSttShort(BaseModel):
    """One short within a multi-short planner response.

    Same shape as ``FullSttClipResponse`` plus ``differentiation_note`` —
    the model's stated reason this short differs from its siblings.
    """

    segments: list[FullSttSegmentPick]
    global_rationale: str = Field(default="", max_length=500)
    differentiation_note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _check_unique_indices(self) -> FullSttShort:
        _require_unique_indices(self.segments)
        return self


class FullSttMultiClipResponse(BaseModel):
    """Top-level shared-planner response: N shorts in one call.

    Per-short structural constraints (index range, chronological order,
    overlap, duration bounds) live in ``picker._validate``, applied to each
    short with the original scene list as context. Cross-short distinctness
    is enforced in ``picker.pick_many`` (a defect there degrades to a
    distinct positional cut, not a hard parse failure).
    """

    shorts: list[FullSttShort]


__all__ = [
    "_RESPONSE_JSON_SCHEMA",
    "FullSttSegmentPick",
    "FullSttClipResponse",
    "FullSttShort",
    "FullSttMultiClipResponse",
    "build_multi_response_schema",
]
