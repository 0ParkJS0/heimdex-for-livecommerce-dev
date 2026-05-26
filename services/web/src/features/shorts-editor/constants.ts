import type { CompositionOutputSpec, SubtitleStyle } from "./lib/types";

// 2026-05-26 — width restored 405 → 406 because contracts 0.18.0's
// strict output validator rejects odd dimensions (libx264 requires
// even width/height — see the 422 ``Dimension 405 is odd …`` the
// renderer surfaced). 406×720 has a 0.13 % aspect drift from the
// 9:16 ideal (0.5639 vs 0.5625) which is invisible at integer-pixel
// resolution and well inside the drift between the editor preview
// surfaces (352×626 ≈ 0.5623, FullscreenOverlay 387×688 = 0.5625).
// Keep height=720 as the canonical reference for stored font/position
// coordinates (the backend renderer, container queries, and font
// presets all assume a 720-tall output canvas).
export const DEFAULT_OUTPUT: CompositionOutputSpec = {
  width: 406,
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
// 2026-05-22 — operator review (Item 11 / D11=A): the editor canvas
// reference is 352×626 (exact 9:16 at integer-pixel resolution) and
// the operator's mental model is "25px in that reference frame."
// Storage stays in 720h output reference coords so the backend PIL
// renderer keeps using the value verbatim; the editor + fullscreen
// previews scale via CSS container queries (see PreviewPanel +
// OverlayRenderer):
//
//   displayed_px = stored_px × (preview_height / 720)
//
// To hit a 25 px displayed target in the 626-tall editor preview the
// stored value is 25 × (720 / 626) ≈ 28.75 → 29. The container-query
// scale already gives the "viewport grows → visible font grows
// proportionally, stored value unchanged" behaviour the operator
// asked for — picking transform:scale vs cqh is an implementation
// detail; both produce the same visual.
export const DEFAULT_SUBTITLE_STYLE: SubtitleStyle = {
  fontFamily: "Pretendard",
  fontSizePx: 29,
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
