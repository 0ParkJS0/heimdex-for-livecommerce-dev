"""Tests for render-fidelity features: layer_order, letterbox, video_transform.

Validates that the CompositionSpec schema accepts the new fields and that the
pipelines render path consumes them correctly.
"""

from __future__ import annotations

import pytest
from PIL import Image

from heimdex_media_contracts.composition import CompositionSpec
from heimdex_media_contracts.composition.schemas import (
    LayerOrderEntry,
    LetterboxSpec,
    VideoTransformSpec,
)


# ---------------------------------------------------------------------------
# Schema parsing tests
# ---------------------------------------------------------------------------


class TestSchemaNewFields:
    """CompositionSpec must accept the new render-fidelity fields."""

    def _base_spec(self, **overrides) -> dict:
        """Minimal valid CompositionSpec dict with optional overrides."""
        data = {
            "output": {
                "width": 720,
                "height": 1280,
                "fps": 30,
                "format": "mp4",
                "background_color": "#000000",
            },
            "scene_clips": [
                {
                    "scene_id": "s1",
                    "video_id": "v1",
                    "source_type": "gdrive",
                    "start_ms": 0,
                    "end_ms": 5000,
                    "timeline_start_ms": 0,
                },
            ],
            "subtitles": [],
        }
        data.update(overrides)
        return data

    def test_layer_order_parsed(self) -> None:
        spec = CompositionSpec(**self._base_spec(
            layer_order=[
                {"kind": "video"},
                {"kind": "letterbox"},
                {"kind": "subtitles"},
                {"kind": "overlay", "id": "ov1"},
            ],
        ))
        assert spec.layer_order is not None
        assert len(spec.layer_order) == 4
        assert spec.layer_order[0].kind == "video"
        assert spec.layer_order[3].kind == "overlay"
        assert spec.layer_order[3].id == "ov1"

    def test_layer_order_absent_is_none(self) -> None:
        spec = CompositionSpec(**self._base_spec())
        assert spec.layer_order is None

    def test_letterbox_parsed(self) -> None:
        spec = CompositionSpec(**self._base_spec(
            letterbox={
                "top_height_pct": 14.0,
                "bottom_height_pct": 14.0,
                "fill_color": "#000000",
                "border_color": "#FFFFFF",
                "border_width_px": 2,
            },
        ))
        assert spec.letterbox is not None
        assert spec.letterbox.top_height_pct == 14.0
        assert spec.letterbox.bottom_height_pct == 14.0
        assert spec.letterbox.fill_color == "#000000"
        assert spec.letterbox.border_color == "#FFFFFF"
        assert spec.letterbox.border_width_px == 2

    def test_letterbox_absent_is_none(self) -> None:
        spec = CompositionSpec(**self._base_spec())
        assert spec.letterbox is None

    def test_letterbox_no_border(self) -> None:
        spec = CompositionSpec(**self._base_spec(
            letterbox={
                "top_height_pct": 10.0,
                "bottom_height_pct": 10.0,
                "fill_color": "#111111",
                "border_color": None,
                "border_width_px": 0,
            },
        ))
        assert spec.letterbox is not None
        assert spec.letterbox.border_color is None

    def test_video_transform_parsed(self) -> None:
        spec = CompositionSpec(**self._base_spec(
            video_transform={"x": 0.5, "y": 0.4, "scale": 1.2},
        ))
        assert spec.video_transform is not None
        assert spec.video_transform.x == 0.5
        assert spec.video_transform.y == 0.4
        assert spec.video_transform.scale == 1.2

    def test_video_transform_absent_is_none(self) -> None:
        spec = CompositionSpec(**self._base_spec())
        assert spec.video_transform is None

    def test_video_transform_default_values(self) -> None:
        spec = CompositionSpec(**self._base_spec(
            video_transform={"x": 0.5, "y": 0.5, "scale": 1.0},
        ))
        vt = spec.video_transform
        assert vt is not None
        assert vt.x == 0.5 and vt.y == 0.5 and vt.scale == 1.0

    def test_all_three_fields_together(self) -> None:
        spec = CompositionSpec(**self._base_spec(
            layer_order=[{"kind": "video"}, {"kind": "letterbox"}],
            letterbox={
                "top_height_pct": 12.0,
                "bottom_height_pct": 12.0,
                "fill_color": "#222222",
            },
            video_transform={"x": 0.3, "y": 0.6, "scale": 0.8},
        ))
        assert spec.layer_order is not None
        assert spec.letterbox is not None
        assert spec.video_transform is not None

    def test_backward_compat_old_spec_no_new_fields(self) -> None:
        """Specs without the new fields must parse cleanly (None defaults)."""
        spec = CompositionSpec(**self._base_spec())
        assert spec.layer_order is None
        assert spec.letterbox is None
        assert spec.video_transform is None
        assert len(spec.scene_clips) == 1


# ---------------------------------------------------------------------------
# Letterbox bake tests
# ---------------------------------------------------------------------------


class TestLetterboxBake:
    """bake_letterbox_png must produce correct RGBA images."""

    def test_bar_dimensions(self) -> None:
        from heimdex_media_pipelines.composition.render import bake_letterbox_png

        lb = LetterboxSpec(
            top_height_pct=14.0,
            bottom_height_pct=14.0,
            fill_color="#000000",
        )
        img = bake_letterbox_png(lb, canvas_width=720, canvas_height=1280)
        assert img.size == (720, 1280)
        assert img.mode == "RGBA"

        # Top bar: pixel at y=10 should be black opaque
        r, g, b, a = img.getpixel((360, 10))
        assert (r, g, b) == (0, 0, 0)
        assert a == 255

        # Middle: pixel at y=640 should be fully transparent
        _, _, _, a = img.getpixel((360, 640))
        assert a == 0

        # Bottom bar: pixel near bottom edge should be black opaque
        r, g, b, a = img.getpixel((360, 1270))
        assert (r, g, b) == (0, 0, 0)
        assert a == 255

    def test_bar_with_border(self) -> None:
        from heimdex_media_pipelines.composition.render import bake_letterbox_png

        lb = LetterboxSpec(
            top_height_pct=10.0,
            bottom_height_pct=10.0,
            fill_color="#000000",
            border_color="#FF0000",
            border_width_px=4,
        )
        img = bake_letterbox_png(lb, canvas_width=720, canvas_height=1280)

        # Inner edge of top bar (y = 10% of 1280 = 128)
        # The border line is drawn at y = 128 - bw//2 = 126
        top_inner_y = int(1280 * 10 / 100) - 4 // 2
        r, g, b, a = img.getpixel((360, top_inner_y))
        assert r == 255  # red border
        assert a == 255

        # Inner edge of bottom bar (y = 1280 - 128 + bw//2 = 1154)
        bot_inner_y = 1280 - int(1280 * 10 / 100) + 4 // 2
        r, g, b, a = img.getpixel((360, bot_inner_y))
        assert r == 255  # red border
        assert a == 255

    def test_no_border_when_border_color_none(self) -> None:
        from heimdex_media_pipelines.composition.render import bake_letterbox_png

        lb = LetterboxSpec(
            top_height_pct=10.0,
            bottom_height_pct=10.0,
            fill_color="#000000",
            border_color=None,
            border_width_px=4,
        )
        img = bake_letterbox_png(lb, canvas_width=720, canvas_height=1280)

        # Inner edge should be black (no red border)
        top_inner_y = int(1280 * 10 / 100) - 1
        r, g, b, a = img.getpixel((360, top_inner_y))
        assert (r, g, b) == (0, 0, 0)

    def test_custom_fill_color(self) -> None:
        from heimdex_media_pipelines.composition.render import bake_letterbox_png

        lb = LetterboxSpec(
            top_height_pct=20.0,
            bottom_height_pct=20.0,
            fill_color="#FF00FF",
        )
        img = bake_letterbox_png(lb, canvas_width=720, canvas_height=1280)

        # Top bar should be magenta
        r, g, b, a = img.getpixel((360, 10))
        assert (r, g, b) == (255, 0, 255)

    def test_zero_height_bars(self) -> None:
        from heimdex_media_pipelines.composition.render import bake_letterbox_png

        lb = LetterboxSpec(
            top_height_pct=0.0,
            bottom_height_pct=0.0,
            fill_color="#000000",
        )
        img = bake_letterbox_png(lb, canvas_width=720, canvas_height=1280)

        # Everything should be transparent
        _, _, _, a = img.getpixel((360, 10))
        assert a == 0
        _, _, _, a = img.getpixel((360, 1270))
        assert a == 0


# ---------------------------------------------------------------------------
# Video transform scale filter tests
# ---------------------------------------------------------------------------


class TestVideoTransformScaleFilter:
    """_build_video_transform_scale_filter must produce valid ffmpeg filters."""

    def _make_clip(self, **overrides):
        from heimdex_media_contracts.composition import SceneClipSpec
        data = {
            "scene_id": "s1",
            "video_id": "v1",
            "source_type": "gdrive",
            "start_ms": 0,
            "end_ms": 5000,
            "timeline_start_ms": 0,
        }
        data.update(overrides)
        return SceneClipSpec(**data)

    def _make_output(self):
        from heimdex_media_contracts.composition import OutputSpec
        return OutputSpec(width=720, height=1280, fps=30, background_color="#000000")

    def test_default_transform_matches_original(self) -> None:
        from heimdex_media_pipelines.composition.render import (
            _build_video_transform_scale_filter,
        )

        clip = self._make_clip()
        output = self._make_output()
        vt = VideoTransformSpec(x=0.5, y=0.5, scale=1.0)

        result = _build_video_transform_scale_filter(0, clip, output, vt)

        # Default: centered, no transform
        assert "scale=720:1280" in result
        assert "pad=720:1280:(ow-iw)/2:(oh-ih)/2" in result
        assert "[s0]" in result

    def test_none_transform_matches_original(self) -> None:
        from heimdex_media_pipelines.composition.render import (
            _build_video_transform_scale_filter,
        )

        clip = self._make_clip()
        output = self._make_output()

        result = _build_video_transform_scale_filter(0, clip, output, None)

        assert "scale=720:1280" in result
        assert "[s0]" in result

    def test_scaled_transform(self) -> None:
        from heimdex_media_pipelines.composition.render import (
            _build_video_transform_scale_filter,
        )

        clip = self._make_clip()
        output = self._make_output()
        vt = VideoTransformSpec(x=0.5, y=0.5, scale=1.5)

        result = _build_video_transform_scale_filter(0, clip, output, vt)

        # 720 * 1.5 = 1080, 1280 * 1.5 = 1920
        assert "scale=1080:1920" in result
        assert "[s0]" in result

    def test_offset_transform(self) -> None:
        from heimdex_media_pipelines.composition.render import (
            _build_video_transform_scale_filter,
        )

        clip = self._make_clip()
        output = self._make_output()
        vt = VideoTransformSpec(x=0.3, y=0.6, scale=1.0)

        result = _build_video_transform_scale_filter(0, clip, output, vt)

        # With non-default x/y but scale=1.0, pad offset changes
        assert "pad=720:1280:" in result
        assert "[s0]" in result

    def test_pts_offset_preserved(self) -> None:
        from heimdex_media_pipelines.composition.render import (
            _build_video_transform_scale_filter,
        )

        clip = self._make_clip(timeline_start_ms=5000)
        output = self._make_output()
        vt = VideoTransformSpec(x=0.5, y=0.5, scale=1.2)

        result = _build_video_transform_scale_filter(0, clip, output, vt)

        assert "setpts=PTS+5.000/TB" in result


# ---------------------------------------------------------------------------
# LayerOrderEntry model tests
# ---------------------------------------------------------------------------


class TestLayerOrderEntry:
    def test_valid_kinds(self) -> None:
        for kind in ("video", "letterbox", "subtitles", "overlay"):
            entry = LayerOrderEntry(kind=kind)
            assert entry.kind == kind
            assert entry.id is None

    def test_overlay_with_id(self) -> None:
        entry = LayerOrderEntry(kind="overlay", id="text-ov-1")
        assert entry.kind == "overlay"
        assert entry.id == "text-ov-1"

    def test_invalid_kind_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LayerOrderEntry(kind="invalid")


# ---------------------------------------------------------------------------
# LetterboxSpec validation tests
# ---------------------------------------------------------------------------


class TestLetterboxSpecValidation:
    def test_valid_letterbox(self) -> None:
        lb = LetterboxSpec(
            top_height_pct=14.0,
            bottom_height_pct=14.0,
            fill_color="#000000",
            border_color="#FFFFFF",
            border_width_px=2,
        )
        assert lb.top_height_pct == 14.0

    def test_height_pct_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LetterboxSpec(top_height_pct=51.0)
        with pytest.raises(ValidationError):
            LetterboxSpec(top_height_pct=-1.0)

    def test_fill_color_validated(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LetterboxSpec(fill_color="notahex")

    def test_border_color_none_valid(self) -> None:
        lb = LetterboxSpec(border_color=None)
        assert lb.border_color is None


# ---------------------------------------------------------------------------
# VideoTransformSpec validation tests
# ---------------------------------------------------------------------------


class TestVideoTransformSpecValidation:
    def test_valid_transform(self) -> None:
        vt = VideoTransformSpec(x=0.3, y=0.7, scale=1.5)
        assert vt.x == 0.3
        assert vt.y == 0.7
        assert vt.scale == 1.5

    def test_defaults(self) -> None:
        vt = VideoTransformSpec()
        assert vt.x == 0.5
        assert vt.y == 0.5
        assert vt.scale == 1.0

    def test_scale_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            VideoTransformSpec(scale=0.0)
        with pytest.raises(ValidationError):
            VideoTransformSpec(scale=6.0)

    def test_anchor_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            VideoTransformSpec(x=-0.1)
        with pytest.raises(ValidationError):
            VideoTransformSpec(y=1.1)
