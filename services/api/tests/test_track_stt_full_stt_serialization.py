"""Tests for full_stt/serialization.py — versioned plan (de)serialize.

Plan: ``.claude/plans/full-stt-shared-planner-2026-05-20.md``

The persisted ``full_stt_plan`` JSONB has a single owner. These tests pin:
  * round-trip fidelity (serialize → deserialize → identical plan)
  * the ``"v"`` version tag is written
  * an unknown version raises PlanSchemaVersionError (defect → fallback)
  * a missing ``"v"`` is treated as version 1 (forward-safe first deploy)
"""

from __future__ import annotations

import pytest

from app.modules.shorts_auto_product.track_stt.full_stt.serialization import (
    PLAN_SCHEMA_VERSION,
    PlanSchemaVersionError,
    deserialize_plan,
    serialize_plan,
)
from app.modules.shorts_auto_product.track_stt.full_stt.types import (
    FullSttClipPlan,
    FullSttSegment,
)


def _plan(*, fallback: bool = False) -> FullSttClipPlan:
    segs = [
        FullSttSegment(
            scene_id=f"sc_{i}",
            source_start_ms=i * 20_000,
            source_end_ms=(i + 1) * 20_000,
            rationale=f"r{i}",
        )
        for i in range(3)
    ]
    return FullSttClipPlan(
        segments=segs,
        total_duration_ms=60_000,
        global_rationale="explains the product",
        fallback_used=fallback,
    )


class TestRoundTrip:
    def test_serialize_then_deserialize_is_identical(self):
        original = _plan()
        restored = deserialize_plan(serialize_plan(original))
        assert restored.total_duration_ms == original.total_duration_ms
        assert restored.global_rationale == original.global_rationale
        assert restored.fallback_used == original.fallback_used
        assert len(restored.segments) == len(original.segments)
        for r, o in zip(restored.segments, original.segments, strict=True):
            assert r.scene_id == o.scene_id
            assert r.source_start_ms == o.source_start_ms
            assert r.source_end_ms == o.source_end_ms
            assert r.rationale == o.rationale

    def test_fallback_flag_preserved(self):
        restored = deserialize_plan(serialize_plan(_plan(fallback=True)))
        assert restored.fallback_used is True

    def test_empty_plan_round_trips(self):
        empty = FullSttClipPlan(
            segments=[], total_duration_ms=0, global_rationale="", fallback_used=True
        )
        restored = deserialize_plan(serialize_plan(empty))
        assert restored.segments == []
        assert restored.is_empty


class TestVersioning:
    def test_serialized_blob_carries_version(self):
        blob = serialize_plan(_plan())
        assert blob["v"] == PLAN_SCHEMA_VERSION

    def test_unknown_version_raises(self):
        blob = serialize_plan(_plan())
        blob["v"] = 999
        with pytest.raises(PlanSchemaVersionError):
            deserialize_plan(blob)

    def test_missing_version_treated_as_v1(self):
        blob = serialize_plan(_plan())
        del blob["v"]
        # Must not raise — missing v is forward-safe (== 1).
        restored = deserialize_plan(blob)
        assert len(restored.segments) == 3
