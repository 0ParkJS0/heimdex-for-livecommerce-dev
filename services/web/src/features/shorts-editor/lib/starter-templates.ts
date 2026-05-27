/**
 * Built-in caption template starters for the editor's 템플릿 tab.
 *
 * Distinct from user-saved presets (WirePreset) — these are
 * hardcoded "ready-made captions" that the operator clicks to drop a
 * fully-styled text overlay onto the canvas in one move. The
 * template specs (text, font, position, stroke, shadow) come from the
 * design team's reference screenshots (Slack #team-uiux 2026-05-18).
 *
 * Position (transform.y) is canvas-height-normalized (0 = top, 1 =
 * bottom). The shared top-anchor lands every starter ~27% down from
 * the top so applying one preset after another lines up visually
 * instead of jumping around.
 */

import type { EditorTextOverlay } from "./overlay-types";

// 2026-05-20 — operator review reverted from the previous absolute-px
// anchor (27px against the 688px phone frame, which rendered ~4% from
// the top) to a true 27% ratio so the title sits closer to the upper-
// third focal point of the canvas. The original design specs
// (254/45/344 px against the phone frame) are dropped in favor of one
// shared ratio.
const UNIFIED_TOP_RATIO = 0.27;

/** Style + text payload for creating a new text overlay from a template. */
export type StarterTemplateStyle = Omit<
  EditorTextOverlay,
  "kind" | "id" | "startMs" | "endMs" | "layerIndex"
>;

export interface StarterTemplate {
  id: string;
  /** Short label rendered under the card. */
  name: string;
  /** Long-form preview text rendered inside the card. */
  previewLabel: string;
  style: StarterTemplateStyle;
}

const CENTERED_TRANSFORM = (topRatio: number) => ({
  x: 0.5,
  y: topRatio,
  rotationDeg: 0,
  widthPx: null,
  heightPx: null,
});

const NO_HIGHLIGHT = {
  highlightColor: null,
  highlightPaddingPx: 0,
  highlightOpacity: 0,
};

const COMMON_TEXT_FIELDS = {
  italic: false,
  underline: false,
  textAlign: "center" as const,
  lineHeight: 1.3,
  letterSpacing: 0,
};

export const STARTER_TEMPLATES: readonly StarterTemplate[] = [
  {
    // Renamed 2026-05-22 — operator picked product-neutral names so the
    // starter list works for any vertical (분리수납/반달/손잡이 were
    // copy that came from the original 라이브 커머스 mock). Underlying
    // style payload unchanged.
    id: "starter-clean-organizer",
    name: "Livenow 1",
    previewLabel: "한눈에 보이는\n분리수납!",
    style: {
      ...COMMON_TEXT_FIELDS,
      ...NO_HIGHLIGHT,
      text: "한눈에 보이는 분리수납!",
      fontFamily: "Onglyph Positive",
      fontSizePx: 38,
      fontWeight: 400,
      fontColor: "#FFFFFF",
      transform: CENTERED_TRANSFORM(UNIFIED_TOP_RATIO),
      effects: {
        opacity: 1,
        stroke: { color: "#000000", widthPx: 1.5 },
        // 80% black — packed as #RRGGBBAA so the renderer's color parser
        // (composition-builder serializer) carries opacity through to
        // the wire shape without needing a separate alpha field.
        shadow: {
          color: "#000000CC",
          offsetX: 1,
          offsetY: 1,
          blurPx: 1,
          spreadPx: 0,
        },
      },
    },
  },
  {
    id: "starter-apsong-crossbag",
    name: "Livenow 2",
    previewLabel: "앱송 반달\n크로스백",
    style: {
      ...COMMON_TEXT_FIELDS,
      ...NO_HIGHLIGHT,
      text: "앱송 반달 크로스백",
      fontFamily: "A2Z",
      // 6SemiBold weight from the A2Z family — mapped to CSS 600.
      fontSizePx: 30,
      fontWeight: 600,
      fontColor: "#2D2007",
      transform: CENTERED_TRANSFORM(UNIFIED_TOP_RATIO),
      effects: {
        opacity: 1,
        stroke: null,
        shadow: null,
      },
    },
  },
  {
    id: "starter-comfortable-handle",
    name: "Livenow 3",
    previewLabel: "손잡이가 있어\n편한~",
    style: {
      ...COMMON_TEXT_FIELDS,
      ...NO_HIGHLIGHT,
      text: "손잡이가 있어 편한~",
      fontFamily: "Pretendard",
      fontSizePx: 32,
      fontWeight: 700,
      fontColor: "#FFFFFF",
      transform: CENTERED_TRANSFORM(UNIFIED_TOP_RATIO),
      effects: {
        opacity: 1,
        stroke: null,
        // 25% black — see the 분리수납 template for the alpha-packing
        // rationale.
        shadow: {
          color: "#00000040",
          offsetX: 1,
          offsetY: 1,
          blurPx: 1,
          spreadPx: 0,
        },
      },
    },
  },
];
