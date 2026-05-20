"""Versioned (de)serialization for the persisted full-STT plan.

``FullSttClipPlan`` is persisted as ``product_scan_jobs.full_stt_plan``
JSONB by the shared planner and read back by the render child. This module
is the SINGLE owner of that on-disk shape — both sides route through
``serialize_plan`` / ``deserialize_plan`` so there is no ad-hoc dict-shaping
at call sites and exactly one place to gate the version.

Versioning: every serialized blob carries ``"v": PLAN_SCHEMA_VERSION``.
``deserialize_plan`` branches on it. An unknown version raises
``PlanSchemaVersionError`` (a defect — the child path treats it as
no-plan and routes to fallback rather than rendering garbage). A missing
``"v"`` is treated as version 1 for forward-safety across the first deploy.

Imports only ``full_stt/types.py`` (keeps ``types.py`` the pure root of the
dependency graph).
"""

from __future__ import annotations

from typing import Any

from app.modules.shorts_auto_product.track_stt.full_stt.types import (
    FullSttClipPlan,
    FullSttSegment,
)

PLAN_SCHEMA_VERSION = 1


class PlanSchemaVersionError(ValueError):
    """Raised when a persisted plan carries an unsupported schema version."""


def serialize_plan(plan: FullSttClipPlan) -> dict[str, Any]:
    """Serialize a ``FullSttClipPlan`` to a version-tagged JSON-safe dict."""
    return {
        "v": PLAN_SCHEMA_VERSION,
        "segments": [
            {
                "scene_id": seg.scene_id,
                "source_start_ms": seg.source_start_ms,
                "source_end_ms": seg.source_end_ms,
                "rationale": seg.rationale,
            }
            for seg in plan.segments
        ],
        "total_duration_ms": plan.total_duration_ms,
        "global_rationale": plan.global_rationale,
        "fallback_used": plan.fallback_used,
    }


def deserialize_plan(data: dict[str, Any]) -> FullSttClipPlan:
    """Rebuild a ``FullSttClipPlan`` from a persisted dict.

    Raises ``PlanSchemaVersionError`` on an unknown version. Missing ``"v"``
    is treated as version 1.
    """
    version = data.get("v", 1)
    if version != PLAN_SCHEMA_VERSION:
        raise PlanSchemaVersionError(
            f"unsupported full_stt plan schema version {version!r} "
            f"(this build understands {PLAN_SCHEMA_VERSION})"
        )

    segments = [
        FullSttSegment(
            scene_id=str(seg["scene_id"]),
            source_start_ms=int(seg["source_start_ms"]),
            source_end_ms=int(seg["source_end_ms"]),
            rationale=str(seg.get("rationale", "")),
        )
        for seg in data.get("segments", [])
    ]
    return FullSttClipPlan(
        segments=segments,
        total_duration_ms=int(data.get("total_duration_ms", 0)),
        global_rationale=str(data.get("global_rationale", "")),
        fallback_used=bool(data.get("fallback_used", False)),
    )


__all__ = [
    "PLAN_SCHEMA_VERSION",
    "PlanSchemaVersionError",
    "serialize_plan",
    "deserialize_plan",
]
