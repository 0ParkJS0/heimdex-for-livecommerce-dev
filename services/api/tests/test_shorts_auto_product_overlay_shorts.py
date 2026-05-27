"""Unit-scope tests for the overlay-driven shorts assembler.

Covers the pure-logic stages -- segment extraction + slot pickers +
silence-aware padding. The source adapters (OpenSearch STT loader,
ffmpeg silence loader) wrap external IO and are not exercised here.

Run locally:

    cd services/api && source .venv/bin/activate && pytest \\
        tests/test_shorts_auto_product_overlay_shorts.py
"""

from __future__ import annotations

import pytest

from app.modules.shorts_auto_product.overlay_shorts.enumeration_result import (
    OverlayAppearance,
    OverlayProduct,
)
from app.modules.shorts_auto_product.overlay_shorts.segment import (
    extract_overlay_segments,
)
from app.modules.shorts_auto_product.overlay_shorts.service import (
    SttSegment,
)
from app.modules.shorts_auto_product.overlay_shorts.shorts_assembler import (
    assemble_shorts_plan,
)


# ---------------------------------------------------------------------------
# Helpers.


def _appearance(scene_id: str, ts_ms: int) -> OverlayAppearance:
    return OverlayAppearance(
        scene_id=scene_id,
        timestamp_ms=ts_ms,
        detector_score=0.5,
        extracted_name="센트룸 우먼 더블업",
        extracted_price=69000,
    )


def _product(
    pid: str = "gd_test_p001",
    appearances: tuple[OverlayAppearance, ...] = (),
    *,
    best_scene_id: str = "s_001",
) -> OverlayProduct:
    return OverlayProduct(
        product_id=pid,
        name="센트룸 우먼 더블업",
        price=69000,
        position="top-left",
        best_scene_id=best_scene_id,
        image_s3_key=None,
        appearances=appearances,
        name_variants=("센트룸 우먼 더블업",),
    )


# ---------------------------------------------------------------------------
# segment.extract_overlay_segments


def test_segment_empty_appearances_yields_no_segments():
    segments = extract_overlay_segments(
        product=_product(appearances=()),
        video_drive_id="gd_test",
        video_duration_s=600.0,
    )
    assert segments == []


def test_segment_single_keyframe_padded_to_min_clip():
    # One appearance at 200s. min_clip_s default is 30s, so window
    # should be ~[185, 215] (centered + bounded by video duration).
    segments = extract_overlay_segments(
        product=_product(appearances=(_appearance("s1", 200_000),)),
        video_drive_id="gd_test",
        video_duration_s=600.0,
    )
    assert len(segments) == 1
    seg = segments[0]
    assert seg.padded is True
    assert seg.n_keyframes_in_segment == 1
    assert seg.clip_start_s == pytest.approx(185.0, abs=0.1)
    assert seg.clip_end_s == pytest.approx(215.0, abs=0.1)


def test_segment_multi_keyframe_uses_padded_span():
    # Two appearances 30s apart. With default 22.5s padding the
    # window is roughly [first - 22.5, last + 22.5].
    segments = extract_overlay_segments(
        product=_product(appearances=(
            _appearance("s1", 100_000),
            _appearance("s2", 130_000),
        )),
        video_drive_id="gd_test",
        video_duration_s=600.0,
    )
    assert len(segments) == 1
    seg = segments[0]
    assert seg.padded is False
    assert seg.n_keyframes_in_segment == 2
    assert seg.clip_start_s == pytest.approx(77.5, abs=0.1)
    assert seg.clip_end_s == pytest.approx(152.5, abs=0.1)


def test_segment_gap_breaks_into_two_segments():
    # 100s gap > default 90s threshold -> two segments.
    segments = extract_overlay_segments(
        product=_product(appearances=(
            _appearance("s1", 100_000),
            _appearance("s2", 200_000),
        )),
        video_drive_id="gd_test",
        video_duration_s=600.0,
    )
    assert len(segments) == 2
    assert segments[0].segment_index == 0
    assert segments[1].segment_index == 1


def test_segment_caps_at_max_clip():
    # Span 200s with default padding would be 245s; cap is 120s.
    segments = extract_overlay_segments(
        product=_product(appearances=(
            _appearance("s1", 100_000),
            _appearance("s2", 150_000),
            _appearance("s3", 300_000),
        )),
        video_drive_id="gd_test",
        video_duration_s=600.0,
        keyframe_gap_ms=200_000,  # collapse all into one segment
    )
    assert len(segments) == 1
    seg = segments[0]
    assert (seg.clip_end_s - seg.clip_start_s) == pytest.approx(120.0, abs=0.1)


# ---------------------------------------------------------------------------
# shorts_assembler.assemble_shorts_plan


def _stt(start_s: float, end_s: float, text: str) -> SttSegment:
    return SttSegment(start_s=start_s, end_s=end_s, text=text)


def test_assembler_basic_four_slots_in_order():
    # Minimal but plausible STT covering hook + product mentions + close.
    stt = [
        _stt(0.0, 3.0, "안녕하세요 여러분"),
        _stt(20.0, 25.0, "오늘 준비한 센트룸 우먼 정말 좋아요"),
        _stt(60.0, 70.0, "센트룸 더블업 흡수가 너무 잘 됩니다"),
        _stt(580.0, 585.0, "오늘도 감사합니다 수고하셨어요"),
    ]
    silences: list[tuple[float, float]] = []
    overlay_seg_list = extract_overlay_segments(
        product=_product(
            appearances=(_appearance("s_001", 65_000),),
            best_scene_id="s_001",
        ),
        video_drive_id="gd_test",
        video_duration_s=600.0,
    )

    assembly = assemble_shorts_plan(
        product=_product(
            appearances=(_appearance("s_001", 65_000),),
            best_scene_id="s_001",
        ),
        overlay_segments=overlay_seg_list,
        stt_segments=stt,
        silences=silences,
        video_duration_s=600.0,
        source_video_locator="s3://bucket/video.mp4",
        target_duration_s=30,
    )

    slot_names = [s.name for s in assembly.slots]
    # narrative order
    assert slot_names[0] == "HOOK"
    assert slot_names[1] == "HERO"
    assert "DEMO" in slot_names[2]
    assert slot_names[-1] == "CLOSE"
    # all slots have positive duration
    for slot in assembly.slots:
        assert slot.end_s > slot.start_s


def test_assembler_hook_picks_greeting_sentence():
    stt = [
        _stt(0.0, 3.0, "안녕하세요 여러분"),
        _stt(5.0, 10.0, "센트룸 더블업"),
        _stt(580.0, 585.0, "감사합니다"),
    ]
    overlay_seg_list = extract_overlay_segments(
        product=_product(appearances=(_appearance("s1", 100_000),)),
        video_drive_id="gd_test",
        video_duration_s=600.0,
    )
    assembly = assemble_shorts_plan(
        product=_product(appearances=(_appearance("s1", 100_000),)),
        overlay_segments=overlay_seg_list,
        stt_segments=stt,
        silences=[],
        video_duration_s=600.0,
        source_video_locator="local://video.mp4",
        target_duration_s=15,
    )
    hook = next(s for s in assembly.slots if s.name == "HOOK")
    assert "안녕" in hook.text


def test_assembler_close_avoids_stopword():
    # Late "정답" sentence should be skipped in favor of a clean
    # close-keyword sentence.
    stt = [
        _stt(0.0, 3.0, "안녕하세요"),
        _stt(30.0, 35.0, "센트룸 더블업 정말 좋아요"),
        _stt(590.0, 595.0, "정답은 5번입니다"),
        _stt(596.0, 600.0, "오늘도 감사합니다"),
    ]
    overlay_seg_list = extract_overlay_segments(
        product=_product(appearances=(_appearance("s1", 30_000),)),
        video_drive_id="gd_test",
        video_duration_s=600.0,
    )
    assembly = assemble_shorts_plan(
        product=_product(appearances=(_appearance("s1", 30_000),)),
        overlay_segments=overlay_seg_list,
        stt_segments=stt,
        silences=[],
        video_duration_s=600.0,
        source_video_locator="local://video.mp4",
        target_duration_s=30,
    )
    close = next(s for s in assembly.slots if s.name == "CLOSE")
    assert "정답" not in close.text
    assert "감사" in close.text


def test_assembler_pad_snaps_to_silence_when_available():
    # The HOOK sentence ends at 3.0s. With a silence interval at
    # [3.4, 3.8] the snapped end should land near the midpoint
    # (~3.6s) rather than the hard-pad fallback (3.0 + 0.25 = 3.25s).
    stt = [
        _stt(0.0, 3.0, "안녕하세요 여러분"),
        _stt(10.0, 15.0, "센트룸 더블업 정말 좋네요"),
        _stt(595.0, 600.0, "감사합니다"),
    ]
    silences = [(3.4, 3.8)]
    overlay_seg_list = extract_overlay_segments(
        product=_product(appearances=(_appearance("s1", 12_000),)),
        video_drive_id="gd_test",
        video_duration_s=600.0,
    )
    assembly = assemble_shorts_plan(
        product=_product(appearances=(_appearance("s1", 12_000),)),
        overlay_segments=overlay_seg_list,
        stt_segments=stt,
        silences=silences,
        video_duration_s=600.0,
        source_video_locator="local://video.mp4",
        target_duration_s=15,
    )
    hook = next(s for s in assembly.slots if s.name == "HOOK")
    # Snapped to ~3.6s (silence midpoint), within tolerance.
    assert hook.end_s == pytest.approx(3.6, abs=0.05)


def test_assembler_rejects_invalid_duration():
    with pytest.raises(ValueError):
        assemble_shorts_plan(
            product=_product(appearances=(_appearance("s1", 100_000),)),
            overlay_segments=[],
            stt_segments=[_stt(0.0, 3.0, "안녕")],
            silences=[],
            video_duration_s=600.0,
            source_video_locator="local://video.mp4",
            target_duration_s=45,  # type: ignore[arg-type]
        )
