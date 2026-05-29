"""Tests for full_stt/prompt.py — pure functions, no I/O.

Plan: ``.claude/plans/storyboard-full-stt-picker-2026-05-20.md``
"""

from __future__ import annotations

from app.modules.shorts_auto_product.track_stt.full_stt.prompt import (
    _MULTI_SYSTEM_PROMPT,
    _SYSTEM_PROMPT,
    MULTI_PROMPT_VERSION,
    PROMPT_VERSION,
    build_grouping_user_prompt,
    build_mention_system_prompt,
    build_mention_user_prompt,
    build_user_prompt,
    group_consecutive_scenes,
    merge_consecutive_scenes,
    select_scenes_for_prompt,
)
from app.modules.shorts_auto_product.track_stt.full_stt.types import FullSttScene


def _scene(idx: int, *, start_ms: int, end_ms: int, text: str = "hello") -> FullSttScene:
    return FullSttScene(scene_id=f"sc_{idx}", start_ms=start_ms, end_ms=end_ms, text=text)


class TestPromptVersion:
    def test_constant_is_v4(self):
        assert PROMPT_VERSION == "v4"

    def test_system_prompt_non_empty(self):
        assert len(_SYSTEM_PROMPT) > 100


class TestMentionSystemPrompt:
    def test_fills_product_name(self):
        out = build_mention_system_prompt("DysonV11")
        assert "DysonV11" in out
        # No literal placeholder may survive into the LLM instructions —
        # leftover {product_name} silently disables the "only this product"
        # constraint (picker.py was sending _SYSTEM_PROMPT raw).
        assert "{product_name}" not in out

    def test_every_placeholder_is_filled(self):
        # _SYSTEM_PROMPT has 5 {product_name} slots; all must be replaced.
        out = build_mention_system_prompt("ACME Blender")
        assert out.count("ACME Blender") == 5


class TestNoSlotKeywords:
    def test_no_hook_in_system_prompt(self):
        low = _SYSTEM_PROMPT.lower()
        assert "hook" not in low

    def test_no_intro_in_system_prompt(self):
        assert "intro" not in _SYSTEM_PROMPT.lower()

    def test_no_cta_in_system_prompt(self):
        assert "cta" not in _SYSTEM_PROMPT.lower()


class TestProductLine:
    def _prompt(self, aliases: list[str]) -> str:
        scenes = [_scene(0, start_ms=0, end_ms=10_000, text="test")]
        return build_user_prompt(
            scenes=scenes,
            target_duration_ms=60_000,
            llm_label="DysonV11",
            spoken_aliases=aliases,
        )

    def test_llm_label_in_prompt(self):
        out = self._prompt([])
        assert "DysonV11" in out

    def test_aliases_included_when_present(self):
        out = self._prompt(["다이슨", "Dyson"])
        assert "다이슨" in out
        assert "Dyson" in out

    def test_blank_aliases_filtered(self):
        out = self._prompt(["", "  ", "다이슨"])
        assert "다이슨" in out
        # No trailing comma or empty parens from blank entries
        assert '""' not in out

    def test_no_aliases_shows_fallback(self):
        out = self._prompt([])
        assert "no aliases" in out

    def test_llm_label_not_duplicated_in_aliases(self):
        # llm_label == an alias → should not appear twice in the alias list
        out = self._prompt(["DysonV11", "다이슨"])
        # "DysonV11" appears once as the product name, not again in aliases
        assert out.count("DysonV11") == 1


class TestTimeFormatting:
    def test_zero_start_formats_correctly(self):
        scenes = [_scene(0, start_ms=0, end_ms=14_000)]
        out = build_user_prompt(
            scenes=scenes, target_duration_ms=60_000,
            llm_label="X", spoken_aliases=[],
        )
        assert "[0] 00:00-00:14" in out

    def test_minutes_and_seconds_format_correctly(self):
        # 4:00 → 4:15
        scenes = [_scene(0, start_ms=240_000, end_ms=255_000)]
        out = build_user_prompt(
            scenes=scenes, target_duration_ms=60_000,
            llm_label="X", spoken_aliases=[],
        )
        assert "[0] 04:00-04:15" in out

    def test_no_milliseconds_in_output(self):
        scenes = [_scene(0, start_ms=1_500, end_ms=15_000)]
        out = build_user_prompt(
            scenes=scenes, target_duration_ms=60_000,
            llm_label="X", spoken_aliases=[],
        )
        assert "1500" not in out
        assert "15000" not in out


class TestChronologicalOrder:
    def test_out_of_order_scenes_are_sorted(self):
        scenes = [
            _scene(0, start_ms=30_000, end_ms=45_000, text="later"),
            _scene(1, start_ms=0, end_ms=15_000, text="earlier"),
        ]
        # select_scenes_for_prompt sorts; build_user_prompt receives sorted input
        capped = select_scenes_for_prompt(scenes, max_scenes=10)
        out = build_user_prompt(
            scenes=capped, target_duration_ms=60_000,
            llm_label="X", spoken_aliases=[],
        )
        idx_00 = out.index("[0] 00:00")
        idx_01 = out.index("[1] 00:30")
        assert idx_00 < idx_01


class TestCap:
    def test_max_scenes_limits_prompt_entries(self):
        scenes = [_scene(i, start_ms=i * 10_000, end_ms=(i + 1) * 10_000) for i in range(10)]
        capped = select_scenes_for_prompt(scenes, max_scenes=5)
        assert len(capped) == 5

    def test_no_cap_when_under_limit(self):
        scenes = [_scene(i, start_ms=i * 10_000, end_ms=(i + 1) * 10_000) for i in range(4)]
        capped = select_scenes_for_prompt(scenes, max_scenes=5)
        assert len(capped) == 4

    def test_prompt_contains_exactly_capped_entries(self):
        scenes = [_scene(i, start_ms=i * 10_000, end_ms=(i + 1) * 10_000) for i in range(10)]
        capped = select_scenes_for_prompt(scenes, max_scenes=5)
        out = build_user_prompt(
            scenes=capped, target_duration_ms=60_000,
            llm_label="X", spoken_aliases=[],
        )
        # Indices are 0-based — should have 5 entries ([0] through [4])
        assert "[4]" in out
        assert "[5]" not in out


class TestMergeConsecutiveScenes:
    def test_groups_consecutive_scenes(self):
        scenes = [
            _scene(i, start_ms=i * 10_000, end_ms=(i + 1) * 10_000, text=f"t{i}")
            for i in range(5)
        ]
        groups = group_consecutive_scenes(scenes, group_size=2)
        assert [[scene.scene_id for scene in group] for group in groups] == [
            ["sc_0", "sc_1"],
            ["sc_2", "sc_3"],
            ["sc_4"],
        ]

    def test_merge_preserves_time_span_and_text_context(self):
        scenes = [
            _scene(0, start_ms=0, end_ms=10_000, text="first"),
            _scene(1, start_ms=10_000, end_ms=20_000, text="second"),
        ]
        merged = merge_consecutive_scenes(scenes, group_size=2)
        assert len(merged) == 1
        assert merged[0].scene_id == "sc_0"
        assert merged[0].start_ms == 0
        assert merged[0].end_ms == 20_000
        assert merged[0].text == "first second"


class TestMultiPrompt:
    def test_multi_prompt_version_is_v5(self):
        assert MULTI_PROMPT_VERSION == "v5"

    def test_multi_system_prompt_non_empty(self):
        assert len(_MULTI_SYSTEM_PROMPT) > 100

    def test_multi_system_prompt_has_no_slot_keywords(self):
        low = _MULTI_SYSTEM_PROMPT.lower()
        assert "hook" not in low
        assert "intro" not in low
        assert "cta" not in low

    def test_multi_system_prompt_asks_for_difference(self):
        # The variety constraint is the whole point of the grouping step.
        assert "different" in _MULTI_SYSTEM_PROMPT.lower()

    def test_multi_system_prompt_groups_existing_regions(self):
        # The grouping prompt must NOT re-define what a mention is — it only
        # partitions already-found regions.
        low = _MULTI_SYSTEM_PROMPT.lower()
        assert "region" in low
        assert "group" in low


class TestGroupingUserPrompt:
    def test_states_count(self):
        regions = [(0, 10_000, "t", "r0")]
        out = build_grouping_user_prompt(
            regions=regions, target_duration_ms=60_000, n=3,
        )
        assert "3 shorts" in out

    def test_lists_regions_with_index_time_text_and_rationale(self):
        regions = [
            (0, 14_000, "hello world", "mentions DysonV11"),
            (30_000, 45_000, "second region", "again DysonV11"),
        ]
        out = build_grouping_user_prompt(
            regions=regions, target_duration_ms=60_000, n=2,
        )
        # Region 0 line: index, timestamp, text, rationale
        assert '[0] 00:00-00:14 "hello world" — mentions DysonV11' in out
        assert '[1] 00:30-00:45 "second region" — again DysonV11' in out

    def test_empty_rationale_omits_dash(self):
        regions = [(0, 14_000, "hello", "")]
        out = build_grouping_user_prompt(
            regions=regions, target_duration_ms=60_000, n=1,
        )
        assert '[0] 00:00-00:14 "hello"' in out
        assert "—" not in out


class TestMentionPrompt:
    def test_chunk_headers_present(self):
        scenes = [
            _scene(i, start_ms=i * 10_000, end_ms=(i + 1) * 10_000, text=f"t{i}")
            for i in range(3)
        ]
        groups = group_consecutive_scenes(scenes, group_size=2)
        out = build_mention_user_prompt(
            scene_groups=groups, llm_label="P", spoken_aliases=[],
        )
        assert "── Chunk 0" in out
        assert "── Chunk 1" in out

    def test_flat_scene_indices_continue_across_chunks(self):
        scenes = [
            _scene(i, start_ms=i * 10_000, end_ms=(i + 1) * 10_000, text=f"t{i}")
            for i in range(5)
        ]
        groups = group_consecutive_scenes(scenes, group_size=2)
        out = build_mention_user_prompt(
            scene_groups=groups, llm_label="P", spoken_aliases=[],
        )
        # 5 scenes across 3 chunks (2,2,1) → scene_idx 0..4 should appear,
        # 5 should not
        for i in range(5):
            assert f"[{i}]" in out
        assert "[5]" not in out

    def test_per_scene_timestamps_visible(self):
        scenes = [
            _scene(0, start_ms=0, end_ms=14_000, text="hi"),
            _scene(1, start_ms=14_000, end_ms=30_000, text="there"),
        ]
        groups = group_consecutive_scenes(scenes, group_size=15)
        out = build_mention_user_prompt(
            scene_groups=groups, llm_label="P", spoken_aliases=[],
        )
        assert "[0] 00:00-00:14" in out
        assert "[1] 00:14-00:30" in out

    def test_product_line_and_aliases(self):
        scenes = [_scene(0, start_ms=0, end_ms=10_000)]
        groups = group_consecutive_scenes(scenes, group_size=15)
        out = build_mention_user_prompt(
            scene_groups=groups, llm_label="DysonV11", spoken_aliases=["다이슨"],
        )
        assert "DysonV11" in out
        assert "다이슨" in out


class TestCapTemporalCoverage:
    def test_capped_output_includes_beginning_middle_end(self):
        # 30 scenes evenly spaced, cap=9 → should cover all thirds
        scenes = [_scene(i, start_ms=i * 10_000, end_ms=(i + 1) * 10_000) for i in range(30)]
        capped = select_scenes_for_prompt(scenes, max_scenes=9)
        assert len(capped) == 9
        starts = [s.start_ms for s in capped]
        # Must have at least one scene from first, middle, and last third
        first_third_max = 30 * 10_000 // 3
        last_third_min = 2 * 30 * 10_000 // 3
        assert any(s < first_third_max for s in starts), "no scene from first third"
        assert any(first_third_max <= s < last_third_min for s in starts), "no scene from middle"
        assert any(s >= last_third_min for s in starts), "no scene from last third"
