"""Tests for full_stt/prompt.py — pure functions, no I/O.

Plan: ``.claude/plans/storyboard-full-stt-picker-2026-05-20.md``
"""

from __future__ import annotations

from app.modules.shorts_auto_product.track_stt.full_stt.prompt import (
    _MULTI_SYSTEM_PROMPT,
    _SYSTEM_PROMPT,
    MULTI_PROMPT_VERSION,
    PROMPT_VERSION,
    build_multi_user_prompt,
    build_user_prompt,
    select_scenes_for_prompt,
)
from app.modules.shorts_auto_product.track_stt.full_stt.types import FullSttScene


def _scene(idx: int, *, start_ms: int, end_ms: int, text: str = "hello") -> FullSttScene:
    return FullSttScene(scene_id=f"sc_{idx}", start_ms=start_ms, end_ms=end_ms, text=text)


class TestPromptVersion:
    def test_constant_is_v3(self):
        assert PROMPT_VERSION == "v3"

    def test_system_prompt_non_empty(self):
        assert len(_SYSTEM_PROMPT) > 100


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


class TestMultiPrompt:
    def test_multi_prompt_version_is_v4(self):
        assert MULTI_PROMPT_VERSION == "v4"

    def test_multi_system_prompt_non_empty(self):
        assert len(_MULTI_SYSTEM_PROMPT) > 100

    def test_multi_system_prompt_has_no_slot_keywords(self):
        low = _MULTI_SYSTEM_PROMPT.lower()
        assert "hook" not in low
        assert "intro" not in low
        assert "cta" not in low

    def test_multi_system_prompt_asks_for_difference(self):
        # The variety constraint is the whole point of the shared planner.
        assert "different" in _MULTI_SYSTEM_PROMPT.lower()

    def test_multi_user_prompt_states_count(self):
        scenes = [_scene(0, start_ms=0, end_ms=10_000, text="t")]
        out = build_multi_user_prompt(
            scenes=scenes, target_duration_ms=60_000,
            llm_label="X", spoken_aliases=[], n=3,
        )
        assert "3 shorts" in out

    def test_multi_user_prompt_includes_transcript_block(self):
        # Reuses build_user_prompt for the transcript — product + scenes present.
        scenes = [_scene(0, start_ms=0, end_ms=14_000, text="hello")]
        out = build_multi_user_prompt(
            scenes=scenes, target_duration_ms=60_000,
            llm_label="DysonV11", spoken_aliases=["다이슨"], n=2,
        )
        assert "DysonV11" in out
        assert "다이슨" in out
        assert "[0] 00:00-00:14" in out


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
