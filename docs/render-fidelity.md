# Render Fidelity Audit — Preview = Fullscreen = Backend Render

Date: 2026-05-23
Branch: feat/video-detail-button-cleanup

## Architecture

The render pipeline flows:
  Editor UI -> composition-builder.ts -> CompositionSpec (POST) -> API -> SQS -> Render Worker (external) -> FFmpeg + PIL

The render worker lives outside this repository. The contract boundary is
`heimdex_media_contracts.composition.schemas.CompositionSpec` (Pydantic v2).

## Gaps Found

### 1. Layer Order (FIXED — frontend + worker)

- **Gap**: The preview uses `state.layerOrder` for z-order (video, letterbox,
  subtitles, overlays in operator-defined order). The CompositionSpec had no
  `layer_order` field; the worker composited in a hard-coded order.
- **Fix**: `composition-builder.ts` now serializes `layer_order` as an array
  of `{kind, id?}` entries. The worker must be updated to read this field
  and composite in the specified order.
- **Status**: Done. Schema in heimdex-media-contracts, rendering in heimdex-media-pipelines.

### 2. Letterbox Bars (FIXED — frontend + worker)

- **Gap**: The preview renders letterbox bars (top/bottom solid color + optional
  inner-edge border stroke). The CompositionSpec had no letterbox field; the
  rendered MP4 never included bars.
- **Fix**: `composition-builder.ts` now serializes `letterbox` with
  `top_height_pct`, `bottom_height_pct`, `fill_color`, `border_color`,
  `border_width_px`. Worker must draw the bars and honor the border.
- **Status**: Done. bake_letterbox_png in heimdex-media-pipelines.

### 3. Video Transform (FIXED — frontend + worker)

- **Gap**: The preview allows dragging/scaling the host video layer
  (`videoTransform.x/y/scale`). The CompositionSpec had no video_transform
  field; the worker always centered the video at default scale.
- **Fix**: `composition-builder.ts` now serializes `video_transform` with
  `x`, `y`, `scale` (omitted when default 0.5/0.5/1 to stay backward
  compatible). Worker must translate the video by `(x - 0.5, y - 0.5)`
  and apply uniform scale.
- **Status**: Done. Custom scale+pad filter in heimdex-media-pipelines.

### 4. Text Wrap — Korean keep-all (PARTIAL — helper implemented, NOT wired)

- **Gap**: Preview CSS uses `word-break: keep-all` + `max-width`. The render
  worker's subtitle path (contracts `_build_drawtext_filter`) only splits on
  pre-existing `\n` — it does not re-wrap. So operator-typed subtitles without
  explicit line breaks can overflow / wrap differently than the preview.
- **Helper**: `heimdex_media_pipelines.composition.text_wrap.wrap_korean()`
  implements eojeol-greedy keep-all wrapping (break at spaces, glyph-break an
  over-long eojeol) measured with the PIL font. It is unit-tested.
- **NOT WIRED**: the render path does not call `wrap_korean` yet. Contracts'
  `_build_drawtext_filter` is PIL-free and cannot measure glyphs, so wiring
  server-side auto-wrap is a separate change (move text measurement into the
  pipelines layer, or pre-wrap in the worker before drawtext is built).
- **Status**: Helper DONE + tested; **wiring into the render path is OPEN.**

### 5. Font Size Scaling (VERIFIED — no gap)

- **Preview**: `fontSizePx` is stored in 720-tall output coords. The preview
  scales via CSS container queries: `displayed = stored * (previewH / 720)`.
- **Backend**: Uses `fontSizePx` directly against the 720-tall canvas.
- **Status**: No gap. Both paths apply the same value at the same canvas size.

### 6. Subtitle Position (VERIFIED — no gap)

- **Preview**: `positionX/Y` are normalized [0,1]. CSS positions at
  `left: positionX * 100%`, `top: positionY * 100%` with transform centering.
- **Backend**: `SubtitleStyleSpec.position_x/y` are [0,1]. Worker multiplies
  by canvas width/height.
- **Status**: No gap.

### 7. Overlay Transform + Effects (VERIFIED — contract covers it)

- **Preview**: Overlays use `transform.x/y` (normalized), `rotation_deg`,
  `width_px/height_px`, plus `effects.opacity/stroke/shadow`.
- **Backend**: `OverlaySpec` in contracts has identical fields: `TransformSpec`
  (x, y, rotation_deg, width_px, height_px) + `EffectsSpec` (opacity,
  StrokeSpec, ShadowSpec). The worker bakes each overlay to a transparent
  PNG via PIL and composites via ffmpeg `overlay=enable='between(t,...)'`.
- **Status**: No gap in the contract. The PIL renderer honors stroke + shadow
  (ShadowSpec includes blur_px + spread_px; the bake renderer uses
  PIL GaussianBlur + dilation).

### 8. Overlay Compositing Order (FIXED)

- **Gap**: Overlays carry `layer_index` which the worker uses to sort before
  compositing. The unified `layer_order` (gap 1) extends this to include
  video, letterbox, and subtitles in the stack.
- **Status**: Done. Worker reads `layer_order` and composites in the
  specified order. Falls back to historical order when absent.

## Summary

| # | Gap | Frontend Fix | Worker Fix |
|---|-----|-------------|------------|
| 1 | Layer order | Done (serialized) | Done (heimdex-media-pipelines render.py) |
| 2 | Letterbox | Done (serialized) | Done (bake_letterbox_png + ffmpeg overlay) |
| 3 | Video transform | Done (serialized) | Done (custom scale+pad filter) |
| 4 | Text wrap (Korean) | N/A | Helper done + tested; **NOT wired** into render path (see §4) |
| 5 | Font size scaling | No gap | N/A |
| 6 | Subtitle position | No gap | N/A |
| 7 | Overlay effects | No gap | N/A |
| 8 | Overlay z-order | Done (via #1) | Done (via layer_order consumption) |

Items 1-3 and 8 are implemented across three repos: heimdex-media-contracts
(schema + filtergraph orchestrator), heimdex-media-pipelines (rendering + PIL
bakes), and heimdex-for-livecommerce-dev (worker tests + CI). Items 5-7 were
verified gap-free and required no changes. Item 4's `wrap_korean` helper is
implemented and unit-tested but is NOT yet called by the render path — wiring
server-side Korean auto-wrap remains open.
