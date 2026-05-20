import type { CompositionOutputSpec, SubtitleStyle } from "./lib/types";

// 2026-05-19 — width nudged from 406 → 405 so the output frame is
// exact 9:16 (405 / 720 = 0.5625). This aligns the rendered MP4
// with the editor preview surfaces, both of which already target
// 9:16: FullscreenOverlay (387×688 = exact 9:16) and EditorLayout
// preview slot (352×626 ≈ exact 9:16 at integer-pixel resolution).
// The one-pixel narrowing has no visible effect on rendered shorts
// but removes the ~0.25% aspect drift operators noticed when
// switching between the editor view, the fullscreen popup, and the
// final exported video.
export const DEFAULT_OUTPUT: CompositionOutputSpec = {
  width: 405,
  height: 720,
  fps: 30,
  format: "mp4",
  background_color: "#000000",
};

// FE default for an operator-added subtitle in the editor. AI-shorts
// captions still come through ``build_auto_shorts_subtitle_style``
// (backend formula at canvas_height=720 → 32px / y=0.82) — this
// constant only controls the "add subtitle" affordance and the fall-
// back synthesis path when ``comp.subtitles`` is empty.
//
// 2026-05-20 — operator review: the editor's manual-add subtitle now
// targets a smaller visual footprint that reads as ~16px in the 1440
// viewport editor preview (preview height ~626). Storage stays in
// output (720h) reference coords so the backend PIL renderer keeps
// using the value verbatim; the editor + fullscreen previews scale
// down via CSS container queries (see PreviewPanel + OverlayRenderer):
//
//   displayed_px = stored_px × (preview_height / 720)
//
// stored 18 → 18 × (626/720) ≈ 15.65 px in the 1440-anchor editor
// preview, which rounds to the requested 16 px target. y=0.80
// matches the new lower-third position the operator picked.
export const DEFAULT_SUBTITLE_STYLE: SubtitleStyle = {
  fontFamily: "Pretendard",
  fontSizePx: 18,
  fontColor: "#000000",
  fontWeight: 700,
  positionX: 0.5,
  positionY: 0.8,
  // White pill on black-text — matches the operator-target screenshot
  // and stays legible against any livecommerce background.
  backgroundColor: "#FFFFFF",
  backgroundOpacity: 0.95,
};

export const ZOOM_PRESETS = [5, 25, 50, 100, 150, 200, 300] as const;
export const DEFAULT_ZOOM = 100; // px per second
// MIN_ZOOM dropped to 5 so the user can collapse a multi-minute video into
// the visible timeline width — useful for grabbing a coarse overview before
// drilling into a clip. 5 px/sec ≈ 1500px for a 5-minute video.
export const MIN_ZOOM = 5;
export const MAX_ZOOM = 300;

export const DEFAULT_SUBTITLE_DURATION_MS = 3000;
export const MAX_COMPOSITION_DURATION_MS = 300_000; // 5 minutes

// Each option's ``value`` must match a key in FONT_FAMILY_CSS_MAP
// (lib/fonts.ts) AND have either a next/font/local block in
// app/fonts.ts or a matching @font-face declaration in
// app/globals.css — otherwise selecting it silently falls back to
// the system default.
export const FONT_OPTIONS = [
  { value: "Pretendard", label: "프리텐다드" },
  { value: "Noto Sans KR", label: "Noto Sans KR" },
  { value: "S-Core Dream", label: "에스코어드림" },
  { value: "NanumSquare", label: "나눔스퀘어" },
  { value: "SUIT", label: "수트(SUIT)" },
  { value: "KoPubWorldDotum", label: "KoPub돋움" },
  // 2026-05-19 — added for the new caption template presets.
  { value: "Onglyph Positive", label: "온글잎 긍정" },
  { value: "A2Z", label: "A2Z (에이투지체)" },
] as const;
