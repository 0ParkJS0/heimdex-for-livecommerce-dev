"""Tests for build_composition_spec_from_full_stt in composition_builder.py.

Plan: ``.claude/plans/storyboard-full-stt-picker-2026-05-20.md``

Pure-function tests. No I/O. Verifies:
  * One SceneClipSpec per FullSttSegment.
  * scene_id is carried through to each SceneClipSpec.
  * timeline_start_ms accumulates correctly.
  * Empty plan raises ValueError.
  * Subtitles are always empty (Whisper post-render provides them).
"""

from __future__ import annotations

import pytest

from app.modules.shorts_auto_product.track_stt.composition_builder import (
    build_composition_spec_from_full_stt,
)
from app.modules.shorts_auto_product.track_stt.full_stt.types import (
    FullSttClipPlan,
    FullSttSegment,
)


def _seg(idx: int, *, start_ms: int, end_ms: int) -> FullSttSegment:
    return FullSttSegment(
        scene_id=f"sc_{idx}",
        source_start_ms=start_ms,
        source_end_ms=end_ms,
        rationale="",
    )


def _plan(*segments: FullSttSegment, fallback_used: bool = False) -> FullSttClipPlan:
    total = sum(s.duration_ms for s in segments)
    return FullSttClipPlan(
        segments=list(segments),
        total_duration_ms=total,
        global_rationale="",
        fallback_used=fallback_used,
    )


class TestOneSceneClipSpecPerSegment:
    def test_four_segments_produce_four_clips(self):
        p = _plan(
            _seg(0, start_ms=0, end_ms=15_000),
            _seg(1, start_ms=20_000, end_ms=35_000),
            _seg(2, start_ms=40_000, end_ms=55_000),
            _seg(3, start_ms=60_000, end_ms=75_000),
        )
        spec = build_composition_spec_from_full_stt(plan=p, os_video_id="gd_test")
        assert len(spec.scene_clips) == 4

    def test_single_segment_produces_one_clip(self):
        p = _plan(_seg(0, start_ms=0, end_ms=20_000))
        spec = build_composition_spec_from_full_stt(plan=p, os_video_id="gd_test")
        assert len(spec.scene_clips) == 1


class TestSceneIdCarriedThrough:
    def test_scene_ids_match_segments(self):
        p = _plan(
            _seg(0, start_ms=0, end_ms=10_000),
            _seg(1, start_ms=20_000, end_ms=30_000),
            _seg(2, start_ms=40_000, end_ms=50_000),
        )
        spec = build_composition_spec_from_full_stt(plan=p, os_video_id="gd_test")
        clip_scene_ids = [c.scene_id for c in spec.scene_clips]
        assert clip_scene_ids == ["sc_0", "sc_1", "sc_2"]

    def test_video_id_carried_to_all_clips(self):
        p = _plan(
            _seg(0, start_ms=0, end_ms=10_000),
            _seg(1, start_ms=20_000, end_ms=30_000),
        )
        spec = build_composition_spec_from_full_stt(plan=p, os_video_id="gd_abc123")
        for clip in spec.scene_clips:
            assert clip.video_id == "gd_abc123"


class TestTimelineStartMs:
    def test_timeline_cursor_accumulates_correctly(self):
        # Segment durations: 10s, 15s, 20s → timeline starts: 0, 10000, 25000
        p = _plan(
            _seg(0, start_ms=0, end_ms=10_000),
            _seg(1, start_ms=20_000, end_ms=35_000),
            _seg(2, start_ms=40_000, end_ms=60_000),
        )
        spec = build_composition_spec_from_full_stt(plan=p, os_video_id="gd_test")
        assert spec.scene_clips[0].timeline_start_ms == 0
        assert spec.scene_clips[1].timeline_start_ms == 10_000
        assert spec.scene_clips[2].timeline_start_ms == 25_000


class TestEmptyPlanRaisesError:
    def test_empty_plan_raises_value_error(self):
        p = FullSttClipPlan(
            segments=[],
            total_duration_ms=0,
            global_rationale="",
        )
        with pytest.raises(ValueError, match="non-empty"):
            build_composition_spec_from_full_stt(plan=p, os_video_id="gd_test")


class TestSubtitlesAlwaysEmpty:
    def test_no_subtitles_emitted(self):
        p = _plan(_seg(0, start_ms=0, end_ms=15_000))
        spec = build_composition_spec_from_full_stt(plan=p, os_video_id="gd_test")
        assert spec.subtitles == []


class TestTitlePassthrough:
    def test_title_none_by_default(self):
        p = _plan(_seg(0, start_ms=0, end_ms=10_000))
        spec = build_composition_spec_from_full_stt(plan=p, os_video_id="gd_test")
        assert spec.title is None

    def test_title_passed_through(self):
        p = _plan(_seg(0, start_ms=0, end_ms=10_000))
        spec = build_composition_spec_from_full_stt(plan=p, os_video_id="gd_test", title="My Short")
        assert spec.title == "My Short"
