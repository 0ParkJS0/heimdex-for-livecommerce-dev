"""OpenAI structured-output schema + Pydantic validators for the full-STT picker.

Two task shapes share this module:

1. **Single-short mention extraction** (``pick``) — returns ALL scene
   ranges where the product is mentioned. Schema: ``_RESPONSE_JSON_SCHEMA``
   + ``FullSttClipResponse``. Range/order/no-overlap checks happen in
   ``picker._validate_mentions``.
2. **Multi-short grouping** (``pick_many`` stage 2) — groups the
   already-extracted mention regions (from stage 1, which reuses the
   single-short ``pick`` extraction) into N distinct shorts. Each short
   references regions by index. Schema: ``build_grouping_response_schema(n)``
   + ``FullSttGroupingResponse``. Per-short region-index/uniqueness checks
   happen in ``picker._validate_grouping_short``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "name": "full_stt_mention_plan",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["mentions", "global_rationale"],
        "properties": {
            "mentions": {
                "type": "array",
                "minItems": 0,
                "maxItems": 50,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["start_scene_idx", "end_scene_idx", "rationale"],
                    "properties": {
                        "start_scene_idx": {"type": "integer", "minimum": 0},
                        "end_scene_idx": {"type": "integer", "minimum": 0},
                        "rationale": {"type": "string", "maxLength": 200},
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


# ── Multi-short grouping schema (pick_many stage 2) ──────────────────
# Stage 2 receives the mention regions found in stage 1 (already indexed
# 0..M-1) and groups them into exactly N shorts. Each short references
# regions by index — no chunk picking, no scene re-detection. The schema
# is built at call time because ``min/maxItems`` on ``shorts`` pin the
# count to the request.

_GROUPING_SHORT_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["region_indices", "global_rationale", "differentiation_note"],
    "properties": {
        "region_indices": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "integer", "minimum": 0},
        },
        "global_rationale": {"type": "string", "maxLength": 500},
        "differentiation_note": {"type": "string", "maxLength": 200},
    },
}


def build_grouping_response_schema(n: int) -> dict[str, Any]:
    """Strict structured-output schema asking for exactly ``n`` shorts.

    ``n`` pins ``shorts`` to ``minItems == maxItems == n`` so the model
    cannot under- or over-produce. ``min/maxItems`` are supported in the
    2026 strict subset (see ``feedback_openai_strict_mode_subset.md``).
    Each short lists ``region_indices`` into the stage-1 mention list.
    """
    return {
        "name": "full_stt_grouping_plan",
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
                    "items": _GROUPING_SHORT_OBJECT_SCHEMA,
                },
            },
        },
    }


class FullSttMention(BaseModel):
    """One mention region returned by the single-short ``pick`` path.

    Both bounds are inclusive scene indices into the per-scene transcript
    shown to the LLM. ``end_scene_idx >= start_scene_idx`` is enforced here;
    range/chronological/overlap checks happen in ``picker._validate_mentions``
    where the original scene list is available as context.
    """

    start_scene_idx: int = Field(ge=0)
    end_scene_idx: int = Field(ge=0)
    rationale: str = Field(default="", max_length=200)

    @field_validator("rationale", mode="before")
    @classmethod
    def _coerce_rationale(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    @model_validator(mode="after")
    def _check_range(self) -> FullSttMention:
        if self.end_scene_idx < self.start_scene_idx:
            raise ValueError(
                f"end_scene_idx ({self.end_scene_idx}) must be >= "
                f"start_scene_idx ({self.start_scene_idx})"
            )
        return self


class FullSttClipResponse(BaseModel):
    """Top-level LLM response for the single-short mention-extraction path.

    Holds the list of mention regions plus an optional global rationale.
    The empty list is valid (product not mentioned anywhere). Range and
    ordering constraints that need the scene list as context live in
    ``picker._validate_mentions``.
    """

    mentions: list[FullSttMention]
    global_rationale: str = Field(default="", max_length=500)


class FullSttGroupingShort(BaseModel):
    """One short within a multi-short grouping response (pick_many stage 2).

    Holds ``region_indices`` — pointers into the stage-1 mention list — plus
    a global rationale and a ``differentiation_note`` (the model's stated
    reason this short differs from its siblings). Index uniqueness is
    enforced here; range / chronological-order / non-overlap checks happen
    in ``picker._validate_grouping_short`` where the mention list is
    available as context.
    """

    region_indices: list[int]
    global_rationale: str = Field(default="", max_length=500)
    differentiation_note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _check_unique_indices(self) -> FullSttGroupingShort:
        if len(set(self.region_indices)) != len(self.region_indices):
            raise ValueError(
                f"region_indices must be unique within a short "
                f"(got {self.region_indices})"
            )
        if not self.region_indices:
            raise ValueError("region_indices must be non-empty")
        return self


class FullSttGroupingResponse(BaseModel):
    """Top-level grouping response (pick_many stage 2): N shorts in one call.

    Per-short region-index range checks live in
    ``picker._validate_grouping_short``, applied with the stage-1 mention
    list as context. Cross-short distinctness is enforced in
    ``picker.pick_many`` (a defect there degrades to a distinct positional
    cut, not a hard parse failure).
    """

    shorts: list[FullSttGroupingShort]


__all__ = [
    "_RESPONSE_JSON_SCHEMA",
    "FullSttMention",
    "FullSttClipResponse",
    "FullSttGroupingShort",
    "FullSttGroupingResponse",
    "build_grouping_response_schema",
]
