"""Tests for Korean keep-all text wrapping (render fidelity Task B).

Verifies that wrap_korean produces line breaks matching CSS
``word-break: keep-all`` + ``max-width: 85%`` semantics.
"""

from __future__ import annotations

import os

import pytest
from PIL import ImageFont

from heimdex_media_pipelines.composition.text_wrap import wrap_korean

# Use the Pretendard-Bold font bundled in the worker's fonts directory.
_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "fonts",
)
_FONT_PATH = os.path.join(_FONT_DIR, "Pretendard-Bold.ttf")


@pytest.fixture
def font() -> ImageFont.FreeTypeFont:
    """Load Pretendard-Bold at 36px (the default subtitle size)."""
    if not os.path.exists(_FONT_PATH):
        pytest.skip(f"Font not found: {_FONT_PATH}")
    return ImageFont.truetype(_FONT_PATH, 36)


# ---------------------------------------------------------------------------
# Basic wrapping
# ---------------------------------------------------------------------------


class TestWrapKoreanBasic:
    def test_single_line_fits(self, font: ImageFont.FreeTypeFont) -> None:
        """Short text that fits in one line stays as one line."""
        text = "안녕하세요"
        lines = wrap_korean(text, font, max_px=600)
        assert lines == ["안녕하세요"]

    def test_empty_text(self, font: ImageFont.FreeTypeFont) -> None:
        lines = wrap_korean("", font, max_px=600)
        assert lines == [""]

    def test_hard_newline_preserved(self, font: ImageFont.FreeTypeFont) -> None:
        text = "첫째 줄\n둘째 줄"
        lines = wrap_korean(text, font, max_px=1000)
        assert lines == ["첫째 줄", "둘째 줄"]

    def test_spaces_only(self, font: ImageFont.FreeTypeFont) -> None:
        text = "   "
        lines = wrap_korean(text, font, max_px=600)
        # Three space-separated empty eojeols
        assert len(lines) >= 1


# ---------------------------------------------------------------------------
# Keep-all wrapping behavior
# ---------------------------------------------------------------------------


class TestWrapKoreanKeepAll:
    def test_wraps_at_space_not_mid_eojeol(
        self, font: ImageFont.FreeTypeFont,
    ) -> None:
        """Must break at a space, never inside a Korean word."""
        text = "프로젝트 마일스톤 달성을 축하드립니다"
        max_px = 400  # Force a wrap

        lines = wrap_korean(text, font, max_px)

        # Should produce 2+ lines
        assert len(lines) >= 2
        # No line should end mid-eojeol — each line is composed of
        # complete space-separated words from the original text.
        all_words = text.split(" ")
        for line in lines:
            for word in line.split(" "):
                assert word in all_words or word == ""

    def test_all_lines_within_budget(
        self, font: ImageFont.FreeTypeFont,
    ) -> None:
        """Every output line must be within max_px (except single-eojeol overflow)."""
        text = "프로젝트 마일스톤 달성을 축하드립니다 정말 감사합니다 여러분"
        max_px = 0.85 * 720  # 612

        lines = wrap_korean(text, font, max_px)

        for line in lines:
            width = font.getlength(line)
            assert width <= max_px + 1, (
                f"Line '{line}' is {width:.1f}px wide, exceeds {max_px:.0f}px"
            )

    def test_canvas_width_720_parity(
        self, font: ImageFont.FreeTypeFont,
    ) -> None:
        """At 85% of 720 canvas, the specific test string should wrap predictably."""
        text = "프로젝트 마일스톤 달성을 축하드립니다"
        max_px = 0.85 * 720  # 612

        lines = wrap_korean(text, font, max_px)

        # Full string is ~554px which fits in 612px
        assert len(lines) == 1
        assert lines[0] == text


# ---------------------------------------------------------------------------
# Long-eojeol fallback (glyph-by-glyph break)
# ---------------------------------------------------------------------------


class TestWrapKoreanLongEojeolFallback:
    def test_single_long_word_glyph_break(
        self, font: ImageFont.FreeTypeFont,
    ) -> None:
        """A single eojeol wider than max_px must break glyph-by-glyph."""
        text = "이것은매우긴하나의단어입니다"
        max_px = 200

        lines = wrap_korean(text, font, max_px)

        # Must produce multiple lines
        assert len(lines) >= 2
        # All lines must be within budget
        for line in lines:
            width = font.getlength(line)
            assert width <= max_px + 1, (
                f"Line '{line}' is {width:.1f}px wide, exceeds {max_px}px"
            )
        # Concatenation must equal original
        assert "".join(lines) == text

    def test_mixed_short_and_long_eojeols(
        self, font: ImageFont.FreeTypeFont,
    ) -> None:
        """Mix of normal eojeols and one too-long eojeol."""
        text = "짧은 이것은매우긴단어입니다 끝"
        max_px = 200

        lines = wrap_korean(text, font, max_px)

        assert len(lines) >= 3
        for line in lines:
            width = font.getlength(line)
            assert width <= max_px + 1


# ---------------------------------------------------------------------------
# Multi-line input
# ---------------------------------------------------------------------------


class TestWrapKoreanMultiLine:
    def test_hard_newlines_and_soft_wraps(
        self, font: ImageFont.FreeTypeFont,
    ) -> None:
        """Hard newlines create line breaks; soft wraps add more."""
        text = "첫째 줄은 매우 긴 문장입니다 이것은 테스트입니다\n둘째 줄"
        max_px = 400

        lines = wrap_korean(text, font, max_px)

        # First hard line should wrap, second should not
        assert len(lines) >= 3
        for line in lines:
            width = font.getlength(line)
            assert width <= max_px + 1

    def test_multiple_hard_newlines(
        self, font: ImageFont.FreeTypeFont,
    ) -> None:
        text = "A\n\nB"
        lines = wrap_korean(text, font, max_px=600)
        assert lines == ["A", "", "B"]
