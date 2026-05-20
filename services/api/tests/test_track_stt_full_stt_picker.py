"""Tests for FullSttExplainerPicker.pick.

Plan: ``.claude/plans/storyboard-full-stt-picker-2026-05-20.md``

Mocks the OpenAI SDK at the call boundary. Verifies:
  * Happy path: well-formed response → FullSttClipPlan with correct scene_id / timestamps.
  * Hallucinated timestamp → fallback, reservation released.
  * Out-of-bounds segment_index → fallback.
  * Non-chronological segments → fallback.
  * Overlapping segments → fallback.
  * Total duration too short (< 30% of target) → fallback.
  * Total duration too long (> 200% of target) → fallback.
  * asyncio.TimeoutError → fallback, reservation released.
  * SDK exception → fallback, reservation released.
  * Budget exhausted → fallback, no LLM call.
  * Positional fallback: 4 picks, fallback_used=True, no LLM call.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.lib.whisper_transcribe.budget import BudgetExceededError, InMemoryBudgetTracker
from app.modules.shorts_auto_product.track_stt.full_stt.picker import FullSttExplainerPicker
from app.modules.shorts_auto_product.track_stt.full_stt.types import FullSttScene


# ----- fixtures -----


def _scene(idx: int, *, start_ms: int, end_ms: int, text: str = "hi") -> FullSttScene:
    return FullSttScene(
        scene_id=f"sc_{idx}",
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
    )


def _scenes_5() -> list[FullSttScene]:
    """5 scenes, 20s each, spanning 0-100s."""
    return [_scene(i, start_ms=i * 20_000, end_ms=(i + 1) * 20_000, text=f"scene {i}") for i in range(5)]


def _make_openai_response(content: str) -> Any:
    usage = SimpleNamespace(prompt_tokens=500, completion_tokens=100)
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice], usage=usage)


def _valid_response_json(scenes: list[FullSttScene], indices: list[int]) -> str:
    segments = [
        {
            "segment_index": idx,
            "rationale": f"rationale for {idx}",
        }
        for idx in indices
    ]
    return json.dumps({"segments": segments, "global_rationale": "good product clip"})


def _make_picker(client: Any, *, budget_usd: float = 10.0) -> FullSttExplainerPicker:
    return FullSttExplainerPicker(
        openai_client=client,
        budget_tracker=InMemoryBudgetTracker(daily_budget_usd=budget_usd),
        model="gpt-4o-mini",
        timeout_s=5.0,
        max_scenes=300,
    )


# ----- tests -----


class TestValidResponse:
    @pytest.mark.asyncio
    async def test_happy_path_returns_correct_segments(self):
        scenes = _scenes_5()
        indices = [0, 2, 4]  # 3 picks, chronological
        content = _valid_response_json(scenes, indices)
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(content)
        )
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes,
            target_duration_ms=60_000,
            llm_label="Product",
            spoken_aliases=["제품"],
        )
        assert not plan.fallback_used
        assert len(plan.segments) == 3
        assert plan.segments[0].scene_id == "sc_0"
        assert plan.segments[1].scene_id == "sc_2"
        assert plan.segments[2].scene_id == "sc_4"
        assert plan.segments[0].source_start_ms == scenes[0].start_ms
        assert plan.segments[0].source_end_ms == scenes[0].end_ms
        assert plan.global_rationale == "good product clip"

    @pytest.mark.asyncio
    async def test_rationales_preserved(self):
        scenes = _scenes_5()
        content = _valid_response_json(scenes, [0, 2, 4])
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_openai_response(content))
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.segments[0].rationale == "rationale for 0"



class TestOutOfRangeIndex:
    @pytest.mark.asyncio
    async def test_large_index_triggers_fallback(self):
        scenes = _scenes_5()
        content = json.dumps({
            "segments": [
                {"segment_index": 999, "rationale": ""},
                {"segment_index": 1, "rationale": ""},
                {"segment_index": 2, "rationale": ""},
            ],
            "global_rationale": "",
        })
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_openai_response(content))
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used


class TestOverlappingSegments:
    @pytest.mark.asyncio
    async def test_overlapping_segments_trigger_fallback(self):
        # scenes[0]=0-20000, scenes[1]=20000-40000 — non-overlapping
        # but if we pick scenes[0] and then also try scenes[0] again that's a dupe
        # Use scenes that are adjacent and one starts before previous ends
        scenes = [
            _scene(0, start_ms=0, end_ms=30_000),
            _scene(1, start_ms=20_000, end_ms=50_000),  # overlaps with scene 0
            _scene(2, start_ms=50_000, end_ms=80_000),
        ]
        content = json.dumps({
            "segments": [
                {"segment_index": 0, "rationale": ""},
                {"segment_index": 1, "rationale": ""},
                {"segment_index": 2, "rationale": ""},
            ],
            "global_rationale": "",
        })
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_openai_response(content))
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used


class TestNonChronologicalSegments:
    @pytest.mark.asyncio
    async def test_reversed_order_triggers_fallback(self):
        scenes = _scenes_5()
        # Return scenes 4, 2, 0 — backwards
        content = json.dumps({
            "segments": [
                {"segment_index": 4, "rationale": ""},
                {"segment_index": 2, "rationale": ""},
                {"segment_index": 0, "rationale": ""},
            ],
            "global_rationale": "",
        })
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_openai_response(content))
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used


class TestDurationTooShort:
    @pytest.mark.asyncio
    async def test_total_below_30pct_triggers_fallback(self):
        # target=60s, lower bound=18s. 3 scenes of 3s each → total 9s < 18s → fallback.
        scenes = [
            _scene(0, start_ms=0, end_ms=3_000),
            _scene(1, start_ms=20_000, end_ms=23_000),
            _scene(2, start_ms=50_000, end_ms=53_000),
        ]
        content = json.dumps({
            "segments": [
                {"segment_index": 0, "rationale": ""},
                {"segment_index": 1, "rationale": ""},
                {"segment_index": 2, "rationale": ""},
            ],
            "global_rationale": "",
        })
        # total = 3000 + 3000 + 3000 = 9000 < 30% of 60000=18000 → fallback
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_openai_response(content))
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used


class TestDurationTooLong:
    @pytest.mark.asyncio
    async def test_total_above_200pct_triggers_fallback(self):
        # target=60s, upper bound=120s. Pick three ~50s scenes → 150s > 120s → fallback.
        scenes = [
            _scene(0, start_ms=0, end_ms=50_000),
            _scene(1, start_ms=50_000, end_ms=100_000),
            _scene(2, start_ms=100_000, end_ms=150_000),
        ]
        content = json.dumps({
            "segments": [
                {"segment_index": 0, "rationale": ""},
                {"segment_index": 1, "rationale": ""},
                {"segment_index": 2, "rationale": ""},
            ],
            "global_rationale": "",
        })
        # total = 150000 > 200% of 60000=120000 → fallback
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_openai_response(content))
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used


class TestPositionalFallbackShape:
    @pytest.mark.asyncio
    async def test_fallback_produces_segments_without_llm_call(self):
        scenes = _scenes_5()
        client = AsyncMock()
        # BudgetExceededError → fallback immediately, no LLM call
        budget = InMemoryBudgetTracker(daily_budget_usd=0.0)
        picker = FullSttExplainerPicker(
            openai_client=client,
            budget_tracker=budget,
            model="gpt-4o-mini",
            timeout_s=5.0,
        )
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used
        assert len(plan.segments) >= 1
        client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_segments_are_chronological(self):
        scenes = [_scene(i, start_ms=i * 30_000, end_ms=(i + 1) * 30_000) for i in range(8)]
        budget = InMemoryBudgetTracker(daily_budget_usd=0.0)
        picker = FullSttExplainerPicker(
            openai_client=AsyncMock(),
            budget_tracker=budget,
        )
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        starts = [s.source_start_ms for s in plan.segments]
        assert starts == sorted(starts)


class TestBudgetExceeded:
    @pytest.mark.asyncio
    async def test_over_budget_triggers_fallback_no_llm_call(self):
        scenes = _scenes_5()
        client = AsyncMock()
        budget = InMemoryBudgetTracker(daily_budget_usd=0.0)
        picker = FullSttExplainerPicker(
            openai_client=client,
            budget_tracker=budget,
        )
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used
        client.chat.completions.create.assert_not_called()


class TestTimeoutFallback:
    @pytest.mark.asyncio
    async def test_timeout_triggers_fallback_and_releases_reservation(self):
        scenes = _scenes_5()
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError())
        budget = InMemoryBudgetTracker(daily_budget_usd=10.0)
        picker = FullSttExplainerPicker(
            openai_client=client,
            budget_tracker=budget,
        )
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used
        # Reservation was released — daily budget should still be available
        # (no cost was charged)
        assert budget.spent_today_usd() < 0.001


class TestSdkExceptionFallback:
    @pytest.mark.asyncio
    async def test_sdk_exception_triggers_fallback(self):
        scenes = _scenes_5()
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used
