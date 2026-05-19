import type { CompositionOutputSpec, SubtitleStyle } from "./lib/types";

export const DEFAULT_OUTPUT: CompositionOutputSpec = {
  width: 406,
  height: 720,
  fps: 30,
  format: "mp4",
  background_color: "#000000",
};

// Mirrors services/api/app/modules/shorts_auto_product/subtitle_layout.py
// ``build_auto_shorts_subtitle_style``. At canvas_height=720 (matches
// ``DEFAULT_OUTPUT.height`` above) the backend formula resolves to
// font_size_px=32, padding≈11, position_y=0.82 with a white pill
// (#FFFFFF @ 0.95) over black bold text. We keep the editor default
// here in lockstep so the operator sees the same visual whether the
// composition came from an auto-rendered short (backend writes the
// style) or from the fallback path that synthesizes subtitles in the
// browser when ``comp.subtitles`` is empty.
export const DEFAULT_SUBTITLE_STYLE: SubtitleStyle = {
  fontFamily: "Pretendard",
  // 720 * 0.045 = 32 — keeps the FE in step with the backend formula
  // so AI-rendered and FE-synthesized subtitles read at the same size.
  fontSizePx: 32,
  fontColor: "#000000",
  fontWeight: 700,
  positionX: 0.5,
  // Backend pins position_y=0.82 so the pill clears the iOS/Android
  // safe-area bars when the short is reposted to social.
  positionY: 0.82,
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
