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
    def _check_unique_indices(self) -> "FullSttClipResponse":
        indices = [s.segment_index for s in self.segments]
        if len(set(indices)) != len(indices):
            raise ValueError(
                f"segment_index must be unique across segments (got {indices})"
            )
        return self


__all__ = [
    "_RESPONSE_JSON_SCHEMA",
    "FullSttSegmentPick",
    "FullSttClipResponse",
]
