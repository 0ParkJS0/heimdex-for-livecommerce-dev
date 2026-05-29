"""Tests for FullSttExplainerPicker.

``pick`` (single-short) extracts every scene range where the product is
mentioned — output is a FullSttClipPlan whose segments ARE the mention
regions (no duration packing). ``pick_many`` (multi-short) is two-stage:
stage 1 reuses the same mention extraction, stage 2 groups the found
regions into N distinct shorts, each packed (mention scenes only) to the
target duration.

Mocks the OpenAI SDK at the call boundary. Verifies:
  * Happy path: well-formed mention response → segments cover the named
    scene ranges with correct scene_id / timestamps.
  * Out-of-bounds scene index → fallback.
  * Non-chronological mention ranges → fallback.
  * Overlapping mention ranges → fallback.
  * Empty mentions list parses fine → empty plan, no fallback.
  * asyncio.TimeoutError → fallback, reservation released.
  * SDK exception → fallback, reservation released.
  * Budget exhausted → fallback, no LLM call.
  * Positional fallback: segments produced, fallback_used=True, no LLM call.
  * pick_many: distinct N shorts, partial-defect handling, dedup, fallback.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.lib.whisper_transcribe.budget import InMemoryBudgetTracker
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


def _mention_response_json(ranges: list[tuple[int, int]]) -> str:
    """Build a mention-schema response with the given inclusive scene ranges."""
    mentions = [
        {
            "start_scene_idx": start,
            "end_scene_idx": end,
            "rationale": f"rationale for [{start},{end}]",
        }
        for start, end in ranges
    ]
    return json.dumps({"mentions": mentions, "global_rationale": "good product clip"})


def _make_picker(client: Any, *, budget_usd: float = 10.0) -> FullSttExplainerPicker:
    return FullSttExplainerPicker(
        openai_client=client,
        budget_tracker=InMemoryBudgetTracker(daily_budget_usd=budget_usd),
        model="gpt-4o-mini",
        timeout_s=5.0,
        max_scenes=300,
        # Per-scene chunking keeps test fixtures (small scene lists) simple —
        # the new mention-extraction path addresses scenes regardless of
        # chunk grouping, so this is purely a prompt-size choice for tests.
        scene_group_size=1,
    )


# ----- tests -----


class TestValidResponse:
    @pytest.mark.asyncio
    async def test_happy_path_returns_segments_for_each_mention_scene(self):
        scenes = _scenes_5()
        # Three single-scene mentions at indices 0, 2, 4.
        content = _mention_response_json([(0, 0), (2, 2), (4, 4)])
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
    async def test_multi_scene_mention_expands_to_one_segment_per_scene(self):
        scenes = _scenes_5()
        # One mention spanning scenes 1..3 inclusive → 3 segments.
        content = _mention_response_json([(1, 3)])
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(content)
        )
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert not plan.fallback_used
        assert [s.scene_id for s in plan.segments] == ["sc_1", "sc_2", "sc_3"]
        assert plan.total_duration_ms == 60_000  # 3 × 20s

    @pytest.mark.asyncio
    async def test_empty_mentions_yields_empty_plan_without_fallback(self):
        scenes = _scenes_5()
        content = _mention_response_json([])
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(content)
        )
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert not plan.fallback_used
        assert plan.segments == []
        assert plan.total_duration_ms == 0

    @pytest.mark.asyncio
    async def test_rationale_propagates_to_every_expanded_segment(self):
        scenes = _scenes_5()
        content = _mention_response_json([(0, 1)])
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(content)
        )
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert plan.segments[0].rationale == "rationale for [0,1]"
        assert plan.segments[1].rationale == "rationale for [0,1]"


class TestOutOfRangeIndex:
    @pytest.mark.asyncio
    async def test_large_end_index_yields_empty_plan(self):
        scenes = _scenes_5()
        # end_scene_idx 999 is way past the 5 active scenes
        content = _mention_response_json([(0, 999)])
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_openai_response(content))
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used
        assert plan.segments == []
        assert plan.error is not None and plan.error.startswith("validation_failed")


class TestOverlappingMentions:
    @pytest.mark.asyncio
    async def test_overlapping_ranges_yield_empty_plan(self):
        scenes = _scenes_5()
        # [0,2] and [2,4] both claim scene 2 → overlap.
        content = _mention_response_json([(0, 2), (2, 4)])
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_openai_response(content))
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used
        assert plan.segments == []
        assert plan.error is not None and plan.error.startswith("validation_failed")


class TestNonChronologicalMentions:
    @pytest.mark.asyncio
    async def test_reversed_order_yields_empty_plan(self):
        scenes = _scenes_5()
        # Two non-overlapping ranges but in reverse temporal order.
        content = _mention_response_json([(3, 4), (0, 1)])
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_openai_response(content))
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used
        assert plan.segments == []
        assert plan.error is not None and plan.error.startswith("validation_failed")


class TestMentionPromptShape:
    @pytest.mark.asyncio
    async def test_prompt_shows_per_scene_lines_under_chunk_headers(self):
        scenes = [
            _scene(i, start_ms=i * 10_000, end_ms=(i + 1) * 10_000)
            for i in range(15)
        ]
        content = _mention_response_json([(0, 0)])
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(return_value=_make_openai_response(content))
        picker = FullSttExplainerPicker(
            openai_client=client,
            budget_tracker=InMemoryBudgetTracker(daily_budget_usd=10.0),
            model="gpt-4o-mini",
            timeout_s=5.0,
            max_scenes=300,
        )
        await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        call = client.chat.completions.create.await_args.kwargs
        user_prompt = call["messages"][1]["content"]
        # Default scene_group_size=15 → 15 scenes form one chunk
        assert "── Chunk 0" in user_prompt
        # Per-scene lines should be present, indexed 0..14
        for i in range(15):
            assert f"[{i}]" in user_prompt


class TestEmptyFailurePlan:
    @pytest.mark.asyncio
    async def test_budget_failure_yields_empty_plan_with_error_no_llm_call(self):
        scenes = _scenes_5()
        client = AsyncMock()
        # BudgetExceededError → empty failure plan, no LLM call
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
        assert plan.segments == []
        assert plan.error is not None
        assert plan.error.startswith("budget_exceeded")
        client.chat.completions.create.assert_not_called()


class TestBudgetExceeded:
    @pytest.mark.asyncio
    async def test_over_budget_yields_empty_plan_no_llm_call(self):
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
        assert plan.segments == []
        client.chat.completions.create.assert_not_called()


class TestTimeoutFailure:
    @pytest.mark.asyncio
    async def test_timeout_yields_empty_plan_and_releases_reservation(self):
        scenes = _scenes_5()
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=TimeoutError())
        budget = InMemoryBudgetTracker(daily_budget_usd=10.0)
        picker = FullSttExplainerPicker(
            openai_client=client,
            budget_tracker=budget,
        )
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used
        assert plan.segments == []
        assert plan.error is not None and plan.error.startswith("api_failure")
        # Reservation was released — daily budget should still be available
        # (no cost was charged)
        assert budget.spent_today_usd() < 0.001


class TestSdkExceptionFailure:
    @pytest.mark.asyncio
    async def test_sdk_exception_yields_empty_plan(self):
        scenes = _scenes_5()
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))
        picker = _make_picker(client)
        plan = await picker.pick(
            scenes=scenes, target_duration_ms=60_000, llm_label="X", spoken_aliases=[]
        )
        assert plan.fallback_used
        assert plan.segments == []
        assert plan.error is not None
        assert "API down" in plan.error


# ----- pick_many (two-stage: extract + group) -----


def _grouping_response_json(region_index_lists: list[list[int]]) -> str:
    """Build a stage-2 grouping response: one short per region-index list."""
    shorts = [
        {
            "region_indices": idxs,
            "global_rationale": "explains the product",
            "differentiation_note": "differs by angle",
        }
        for idxs in region_index_lists
    ]
    return json.dumps({"shorts": shorts})


def _two_stage_client(
    mention_ranges: list[tuple[int, int]],
    region_index_lists: list[list[int]],
) -> Any:
    """Mock OpenAI whose two ``create`` calls return stage-1 mentions then
    stage-2 grouping (``pick_many`` makes the calls in that order)."""
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        side_effect=[
            _make_openai_response(_mention_response_json(mention_ranges)),
            _make_openai_response(_grouping_response_json(region_index_lists)),
        ]
    )
    return client


def _sigs(plans) -> set:
    return {tuple(s.scene_id for s in p.segments) for p in plans}


class TestPickManyHappyPath:
    @pytest.mark.asyncio
    async def test_three_distinct_shorts(self):
        scenes = _scenes_5()
        # Stage 1 finds 3 single-scene mention regions; stage 2 puts each in
        # its own short.
        client = _two_stage_client([(0, 0), (2, 2), (4, 4)], [[0], [1], [2]])
        picker = _make_picker(client)
        plans = await picker.pick_many(
            scenes=scenes, target_duration_ms=60_000, llm_label="P",
            spoken_aliases=["제품"], n=3,
        )
        assert len(plans) == 3
        assert all(not p.fallback_used for p in plans)
        assert len(_sigs(plans)) == 3  # all distinct
        # two LLM calls: stage-1 extraction + stage-2 grouping
        assert client.chat.completions.create.await_count == 2
        # each short is built from its assigned mention scene only
        assert _sigs(plans) == {("sc_0",), ("sc_2",), ("sc_4",)}

    @pytest.mark.asyncio
    async def test_returns_exactly_n_plans(self):
        scenes = _scenes_5()
        client = _two_stage_client([(0, 1), (2, 3), (4, 4)], [[0, 1], [2]])
        picker = _make_picker(client)
        plans = await picker.pick_many(
            scenes=scenes, target_duration_ms=60_000, llm_label="X",
            spoken_aliases=[], n=2,
        )
        assert len(plans) == 2
        assert all(not p.fallback_used for p in plans)

    @pytest.mark.asyncio
    async def test_short_packs_mention_scenes_to_target(self):
        # Stage-1 region 0 spans scenes 0..3 = 80s; with a 60s target the
        # packer keeps 60s of mention scenes (scenes 0..2) and drops the rest.
        scenes = _scenes_5()
        client = _two_stage_client([(0, 3), (4, 4)], [[0], [1]])
        picker = _make_picker(client)
        plans = await picker.pick_many(
            scenes=scenes, target_duration_ms=60_000, llm_label="X",
            spoken_aliases=[], n=2,
        )
        assert plans[0].total_duration_ms == 60_000
        assert [s.scene_id for s in plans[0].segments] == ["sc_0", "sc_1", "sc_2"]


class TestPickManyPartialDefect:
    @pytest.mark.asyncio
    async def test_one_bad_short_falls_back_others_preserved(self):
        scenes = _scenes_5()
        # middle short references an out-of-range region index → only it
        # falls back to a positional cut
        client = _two_stage_client(
            [(0, 0), (2, 2), (4, 4)], [[0], [999], [2]]
        )
        picker = _make_picker(client)
        plans = await picker.pick_many(
            scenes=scenes, target_duration_ms=60_000, llm_label="X",
            spoken_aliases=[], n=3,
        )
        assert [p.fallback_used for p in plans] == [False, True, False]
        assert len(_sigs(plans)) == 3


class TestPickManyDistinctness:
    @pytest.mark.asyncio
    async def test_duplicate_short_is_replaced(self):
        scenes = _scenes_5()
        # short 2 reuses the same region set as short 1 → deduped to a
        # distinct positional cut
        client = _two_stage_client(
            [(0, 0), (2, 2), (4, 4)], [[0], [0], [2]]
        )
        picker = _make_picker(client)
        plans = await picker.pick_many(
            scenes=scenes, target_duration_ms=60_000, llm_label="X",
            spoken_aliases=[], n=3,
        )
        assert plans[1].fallback_used is True
        assert len(_sigs(plans)) == 3


class TestPickManyWholeCallFallback:
    @pytest.mark.asyncio
    async def test_stage1_timeout_yields_n_distinct_positional_and_releases_budget(self):
        scenes = _scenes_5()
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=TimeoutError())
        budget = InMemoryBudgetTracker(daily_budget_usd=10.0)
        picker = FullSttExplainerPicker(
            openai_client=client, budget_tracker=budget,
            model="gpt-4o-mini", timeout_s=5.0, max_scenes=300,
        )
        plans = await picker.pick_many(
            scenes=scenes, target_duration_ms=60_000, llm_label="X",
            spoken_aliases=[], n=3,
        )
        assert len(plans) == 3
        assert all(p.fallback_used for p in plans)
        assert len(_sigs(plans)) == 3
        assert budget.spent_today_usd() < 0.001  # reservation released

    @pytest.mark.asyncio
    async def test_no_mentions_yields_positional_without_grouping_call(self):
        # Stage 1 succeeds but finds nothing → no stage-2 call, N positional.
        scenes = _scenes_5()
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(_mention_response_json([]))
        )
        picker = _make_picker(client)
        plans = await picker.pick_many(
            scenes=scenes, target_duration_ms=60_000, llm_label="X",
            spoken_aliases=[], n=3,
        )
        assert len(plans) == 3
        assert all(p.fallback_used for p in plans)
        # only the stage-1 extraction call was made
        assert client.chat.completions.create.await_count == 1

    @pytest.mark.asyncio
    async def test_stage2_failure_yields_positional(self):
        # Stage 1 finds mentions, stage 2 times out → N positional plans.
        scenes = _scenes_5()
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(
            side_effect=[
                _make_openai_response(_mention_response_json([(0, 0), (2, 2)])),
                TimeoutError(),
            ]
        )
        picker = _make_picker(client)
        plans = await picker.pick_many(
            scenes=scenes, target_duration_ms=60_000, llm_label="X",
            spoken_aliases=[], n=3,
        )
        assert len(plans) == 3
        assert all(p.fallback_used for p in plans)
        assert client.chat.completions.create.await_count == 2

    @pytest.mark.asyncio
    async def test_budget_exceeded_yields_positional_no_llm_call(self):
        scenes = _scenes_5()
        client = AsyncMock()
        picker = FullSttExplainerPicker(
            openai_client=client,
            budget_tracker=InMemoryBudgetTracker(daily_budget_usd=0.0),
        )
        plans = await picker.pick_many(
            scenes=scenes, target_duration_ms=60_000, llm_label="X",
            spoken_aliases=[], n=3,
        )
        assert len(plans) == 3
        assert all(p.fallback_used for p in plans)
        client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_n_returns_empty(self):
        scenes = _scenes_5()
        client = AsyncMock()
        picker = _make_picker(client)
        plans = await picker.pick_many(
            scenes=scenes, target_duration_ms=60_000, llm_label="X",
            spoken_aliases=[], n=0,
        )
        assert plans == []
        client.chat.completions.create.assert_not_called()
