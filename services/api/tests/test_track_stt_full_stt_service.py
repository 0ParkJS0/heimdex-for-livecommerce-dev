"""Tests for assemble_full_stt_clip in track_stt/service.py.

Plan: ``.claude/plans/storyboard-full-stt-picker-2026-05-20.md``

Strategy: every external dep (OS client, picker, render enqueue) is a fake.
No network. Tests run in <100ms.

Verifies:
  * Returns SttClipResult with populated render_job_id and full_stt_plan.
  * selected_chunks is always [] (old pipeline not used).
  * mention_extractor.find_mentioned_scenes is never called.
  * chunk_scorer.score_segment_chunks is never called.
  * segment_assembler.group_into_segments is never called.
  * live_only=True → scene_id_allowlist filters fetched scenes.
  * All-empty transcript raises TranscriptUnavailableError.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.modules.shorts_auto_product.track_stt import (
    chunk_scorer,
    mention_extractor,
    segment_assembler,
    service,
)
from app.modules.shorts_auto_product.track_stt.errors import TranscriptUnavailableError
from app.modules.shorts_auto_product.track_stt.full_stt.types import (
    FullSttClipPlan,
    FullSttSegment,
)

# ----- fake OS client -----


class _FakeOSClient:
    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self._hits = hits
        self.call_count = 0

    async def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        return {"hits": {"hits": [{"_source": h} for h in self._hits]}}


def _scene_hit(
    scene_id: str,
    *,
    start_ms: int,
    end_ms: int,
    text: str = "제품 설명",
    speech_segment_count: int = 3,
) -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "transcript_raw": text,
        "speaker_transcript": "",
        "speech_segment_count": speech_segment_count,
    }


def _five_hits() -> list[dict[str, Any]]:
    return [_scene_hit(f"sc_{i}", start_ms=i * 20_000, end_ms=(i + 1) * 20_000) for i in range(5)]


def _make_plan(n: int = 3) -> FullSttClipPlan:
    segs = [
        FullSttSegment(
            scene_id=f"sc_{i}",
            source_start_ms=i * 20_000,
            source_end_ms=(i + 1) * 20_000,
            rationale="test",
        )
        for i in range(n)
    ]
    return FullSttClipPlan(
        segments=segs,
        total_duration_ms=n * 20_000,
        global_rationale="test plan",
        fallback_used=False,
    )


# ----- helpers -----


async def _fake_enqueue(spec: Any) -> UUID:
    return uuid4()


def _make_picker(plan: FullSttClipPlan) -> Any:
    picker = AsyncMock()
    picker.pick = AsyncMock(return_value=plan)
    return picker


# ----- tests -----


class TestReturnsRenderJobId:
    @pytest.mark.asyncio
    async def test_happy_path_returns_result(self):
        os_client = _FakeOSClient(_five_hits())
        plan = _make_plan()
        picker = _make_picker(plan)

        with patch.object(
            service.composition_builder,
            "build_composition_spec_from_full_stt",
            return_value=MagicMock(),
        ):
            result = await service.assemble_full_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="다이슨 V11",
                spoken_aliases=["다이슨", "V11"],
                os_video_id="gd_test123",
                target_duration_ms=60_000,
                title="test",
                os_client=os_client,
                openai_client=AsyncMock(),
                enqueue_render=_fake_enqueue,
                picker=picker,
                live_only=False,
            )

        assert isinstance(result.render_job_id, UUID)
        assert result.full_stt_plan is plan
        assert result.selected_chunks == []


class TestSelectedChunksAlwaysEmpty:
    @pytest.mark.asyncio
    async def test_selected_chunks_is_empty_list(self):
        os_client = _FakeOSClient(_five_hits())
        picker = _make_picker(_make_plan())

        with patch.object(
            service.composition_builder,
            "build_composition_spec_from_full_stt",
            return_value=MagicMock(),
        ):
            result = await service.assemble_full_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="X",
                spoken_aliases=[],
                os_video_id="gd_test",
                target_duration_ms=60_000,
                title=None,
                os_client=os_client,
                openai_client=AsyncMock(),
                enqueue_render=_fake_enqueue,
                picker=picker,
                live_only=False,
            )

        assert result.selected_chunks == []


class TestSkipsMentionExtraction:
    @pytest.mark.asyncio
    async def test_find_mentioned_scenes_not_called(self):
        os_client = _FakeOSClient(_five_hits())
        picker = _make_picker(_make_plan())

        with (
            patch.object(mention_extractor, "find_mentioned_scenes") as mock_find,
            patch.object(
                service.composition_builder,
                "build_composition_spec_from_full_stt",
                return_value=MagicMock(),
            ),
        ):
            await service.assemble_full_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="X",
                spoken_aliases=[],
                os_video_id="gd_test",
                target_duration_ms=60_000,
                title=None,
                os_client=os_client,
                openai_client=AsyncMock(),
                enqueue_render=_fake_enqueue,
                picker=picker,
                live_only=False,
            )

        mock_find.assert_not_called()


class TestSkipsChunkScoring:
    @pytest.mark.asyncio
    async def test_score_segment_chunks_not_called(self):
        os_client = _FakeOSClient(_five_hits())
        picker = _make_picker(_make_plan())

        with (
            patch.object(chunk_scorer, "score_segment_chunks", MagicMock()) as mock_score,
            patch.object(
                service.composition_builder,
                "build_composition_spec_from_full_stt",
                return_value=MagicMock(),
            ),
        ):
            await service.assemble_full_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="X",
                spoken_aliases=[],
                os_video_id="gd_test",
                target_duration_ms=60_000,
                title=None,
                os_client=os_client,
                openai_client=AsyncMock(),
                enqueue_render=_fake_enqueue,
                picker=picker,
                live_only=False,
            )

        mock_score.assert_not_called()


class TestSkipsSegmentAssembly:
    @pytest.mark.asyncio
    async def test_group_into_segments_not_called(self):
        os_client = _FakeOSClient(_five_hits())
        picker = _make_picker(_make_plan())

        with (
            patch.object(segment_assembler, "group_into_segments", MagicMock()) as mock_group,
            patch.object(
                service.composition_builder,
                "build_composition_spec_from_full_stt",
                return_value=MagicMock(),
            ),
        ):
            await service.assemble_full_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="X",
                spoken_aliases=[],
                os_video_id="gd_test",
                target_duration_ms=60_000,
                title=None,
                os_client=os_client,
                openai_client=AsyncMock(),
                enqueue_render=_fake_enqueue,
                picker=picker,
                live_only=False,
            )

        mock_group.assert_not_called()


class TestEmptyTranscriptRaisesError:
    @pytest.mark.asyncio
    async def test_all_empty_text_raises_transcript_unavailable(self):
        hits = [
            _scene_hit(f"sc_{i}", start_ms=i * 10_000, end_ms=(i + 1) * 10_000, text="")
            for i in range(3)
        ]
        os_client = _FakeOSClient(hits)
        picker = _make_picker(_make_plan())

        with pytest.raises(TranscriptUnavailableError):
            await service.assemble_full_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="X",
                spoken_aliases=[],
                os_video_id="gd_test",
                target_duration_ms=60_000,
                title=None,
                os_client=os_client,
                openai_client=AsyncMock(),
                enqueue_render=_fake_enqueue,
                picker=picker,
                live_only=False,
            )


class TestLiveBlockAllowlistRespected:
    @pytest.mark.asyncio
    async def test_live_only_excludes_silent_scenes(self):
        # 4 scenes: only sc_1 and sc_2 have speech (speech_segment_count > 0)
        # live_only=True should filter out sc_0 and sc_3
        hits = [
            _scene_hit("sc_0", start_ms=0, end_ms=10_000, text="", speech_segment_count=0),
            _scene_hit(
                "sc_1", start_ms=10_000, end_ms=30_000, text="live content", speech_segment_count=5
            ),
            _scene_hit(
                "sc_2", start_ms=30_000, end_ms=60_000, text="more live", speech_segment_count=3
            ),
            _scene_hit("sc_3", start_ms=60_000, end_ms=70_000, text="", speech_segment_count=0),
        ]
        os_client = _FakeOSClient(hits)
        received_scenes: list[Any] = []

        async def _capture_pick(**kwargs: Any) -> FullSttClipPlan:
            received_scenes.extend(kwargs["scenes"])
            return _make_plan(2)

        picker = AsyncMock()
        picker.pick = _capture_pick

        with patch.object(
            service.composition_builder,
            "build_composition_spec_from_full_stt",
            return_value=MagicMock(),
        ):
            await service.assemble_full_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="X",
                spoken_aliases=[],
                os_video_id="gd_test",
                target_duration_ms=10_000,
                title=None,
                os_client=os_client,
                openai_client=AsyncMock(),
                enqueue_render=_fake_enqueue,
                picker=picker,
                live_only=True,
            )

        # Only live scenes (sc_1, sc_2) should reach the picker
        scene_ids = {s.scene_id for s in received_scenes}
        assert "sc_0" not in scene_ids
        assert "sc_3" not in scene_ids
        assert "sc_1" in scene_ids
        assert "sc_2" in scene_ids


class TestPurchasePlannerSwitch:
    @pytest.mark.asyncio
    async def test_purchase_planner_uses_ocr_caption_and_bypasses_picker(self):
        hits = [
            {
                "scene_id": "sc_0",
                "start_ms": 0,
                "end_ms": 15_000,
                "transcript_raw": "",
                "speaker_transcript": "",
                "ocr_text_raw": "fwee Smoothie Lip Balm",
                "scene_caption": "host applies lip balm color texture",
                "speech_segment_count": 0,
            },
            {
                "scene_id": "sc_1",
                "start_ms": 15_000,
                "end_ms": 30_000,
                "transcript_raw": "",
                "speaker_transcript": "",
                "ocr_text_raw": "Smoothie Lip Balm color chart",
                "scene_caption": "soft lip balm application demo",
                "speech_segment_count": 0,
            },
            {
                "scene_id": "sc_2",
                "start_ms": 30_000,
                "end_ms": 45_000,
                "transcript_raw": "",
                "speaker_transcript": "",
                "ocr_text_raw": "fwee limited sale",
                "scene_caption": "product package and color benefit",
                "speech_segment_count": 0,
            },
        ]
        os_client = _FakeOSClient(hits)
        picker = AsyncMock()
        picker.pick_many = AsyncMock(side_effect=AssertionError("picker should not run"))

        plans = await service.plan_full_stt_clips(
            org_id=uuid4(),
            catalog_entry_id=uuid4(),
            llm_label="fwee Smoothie Lip Balm",
            spoken_aliases=["fwee", "Smoothie", "Lip Balm"],
            os_video_id="gd_test",
            target_duration_ms=45_000,
            os_client=os_client,
            picker=picker,
            n=1,
            purchase_planner_enabled=True,
        )

        assert len(plans) == 1
        assert plans[0].fallback_used is False
        assert [s.scene_id for s in plans[0].segments] == ["sc_0", "sc_1", "sc_2"]
        picker.pick_many.assert_not_called()

    @pytest.mark.asyncio
    async def test_purchase_story_mode_uses_story_planner_and_bypasses_picker(self):
        hits = [
            {
                "scene_id": "sc_0",
                "start_ms": 0,
                "end_ms": 15_000,
                "transcript_raw": "립밤 컬러 립밤 오늘 보여드릴게요 컬러가 예뻐요",
                "ocr_text_raw": "",
                "scene_caption": "",
                "speech_segment_count": 1,
            },
            {
                "scene_id": "sc_1",
                "start_ms": 15_000,
                "end_ms": 30_000,
                "transcript_raw": "사은품 선물 이벤트 드려요",
                "ocr_text_raw": "",
                "scene_caption": "",
                "speech_segment_count": 1,
            },
            {
                "scene_id": "sc_2",
                "start_ms": 30_000,
                "end_ms": 45_000,
                "transcript_raw": "립밤 컬러 립밤 발림이 부드럽고 촉촉합니다",
                "ocr_text_raw": "",
                "scene_caption": "",
                "speech_segment_count": 1,
            },
            {
                "scene_id": "sc_3",
                "start_ms": 45_000,
                "end_ms": 60_000,
                "transcript_raw": "가디건도 가격이 좋습니다",
                "ocr_text_raw": "",
                "scene_caption": "",
                "speech_segment_count": 1,
            },
            {
                "scene_id": "sc_4",
                "start_ms": 60_000,
                "end_ms": 75_000,
                "transcript_raw": "립밤 컬러 립밤 데일리로 쓰기 좋아서 추천드려요",
                "ocr_text_raw": "",
                "scene_caption": "",
                "speech_segment_count": 1,
            },
        ]
        os_client = _FakeOSClient(hits)
        picker = AsyncMock()
        picker.pick_many = AsyncMock(side_effect=AssertionError("picker should not run"))

        plans = await service.plan_full_stt_clips(
            org_id=uuid4(),
            catalog_entry_id=uuid4(),
            llm_label="립밤",
            spoken_aliases=["컬러 립밤"],
            os_video_id="gd_test",
            target_duration_ms=45_000,
            os_client=os_client,
            picker=picker,
            n=1,
            purchase_planner_enabled=True,
            purchase_planner_mode="story",
            sibling_products=[{"label": "가디건", "aliases": ["니트 가디건"]}],
        )

        assert len(plans) == 1
        assert plans[0].fallback_used is False
        assert [s.scene_id for s in plans[0].segments] == ["sc_0", "sc_2", "sc_4"]
        assert "Story purchase plan" in plans[0].global_rationale
        picker.pick_many.assert_not_called()

    @pytest.mark.asyncio
    async def test_purchase_story_mode_expands_120s_target_and_bypasses_picker(self):
        hits = [
            {
                "scene_id": f"sc_{i}",
                "start_ms": i * 15_000,
                "end_ms": (i + 1) * 15_000,
                "transcript_raw": (
                    f"립밤 컬러 립밤 보여드릴게요 발림이 부드럽고 "
                    f"색상 활용이 좋아서 추천드려요 {i}"
                ),
                "ocr_text_raw": "",
                "scene_caption": "",
                "speech_segment_count": 1,
            }
            for i in range(8)
        ]
        os_client = _FakeOSClient(hits)
        picker = AsyncMock()
        picker.pick_many = AsyncMock(side_effect=AssertionError("picker should not run"))

        plans = await service.plan_full_stt_clips(
            org_id=uuid4(),
            catalog_entry_id=uuid4(),
            llm_label="립밤",
            spoken_aliases=["컬러 립밤"],
            os_video_id="gd_test",
            target_duration_ms=120_000,
            os_client=os_client,
            picker=picker,
            n=1,
            purchase_planner_enabled=True,
            purchase_planner_mode="story",
        )

        assert len(plans) == 1
        assert plans[0].fallback_used is False
        assert plans[0].total_duration_ms >= 102_000
        assert len(plans[0].segments) >= 7
        picker.pick_many.assert_not_called()
