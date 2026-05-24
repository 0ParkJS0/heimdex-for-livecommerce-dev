/**
 * Default factories for V2 overlays.
 *
 * Used by the reducer when adding a new overlay (Add Text / Add Background
 * buttons) and by tests as fixture seeds. Returned objects pass round-trip
 * validation against contracts 0.12.0 — keep them aligned.
 */

import type {
  EditorBackgroundOverlay,
  EditorTextOverlay,
  EffectsProps,
  TransformProps,
} from "./overlay-types";

let _overlayCounter = 0;
export function generateOverlayId(prefix: "text" | "bg" = "text"): string {
  return `ov_${prefix}_${Date.now()}_${++_overlayCounter}`;
}

export const DEFAULT_OVERLAY_DURATION_MS = 3000;

// ---------------------------------------------------------------------------
// Sub-component defaults
// ---------------------------------------------------------------------------

export const DEFAULT_TRANSFORM: TransformProps = {
  x: 0.5,
  y: 0.5,
  rotationDeg: 0,
  widthPx: null,
  heightPx: null,
};

export const DEFAULT_EFFECTS: EffectsProps = {
  opacity: 1.0,
  stroke: null,
  shadow: null,
};

// ---------------------------------------------------------------------------
// TextOverlay default
// ---------------------------------------------------------------------------

export function createDefaultTextOverlay(args: {
  startMs: number;
  endMs?: number;
  layerIndex?: number;
}): EditorTextOverlay {
  return {
    kind: "text",
    id: generateOverlayId("text"),
    startMs: args.startMs,
    endMs: args.endMs ?? args.startMs + DEFAULT_OVERLAY_DURATION_MS,
    layerIndex: args.layerIndex ?? 0,
    // 2026-05-22 — '텍스트 추가' default (Figma 2031:328972 / user
    // spec): centered horizontally at 0.5, 10 % down from the top so a
    // freshly added overlay sits in the upper third of the canvas
    // (close to the title position the operator sees in the Figma
    // mock). Previously y=0.85 mimicked the legacy lower-third
    // subtitle baseline, which collided with the host-STT subtitle
    // row on the canvas.
    transform: { ...DEFAULT_TRANSFORM, x: 0.5, y: 0.1 },
    effects: { ...DEFAULT_EFFECTS },
    // Default text body lets the operator see the overlay
    // immediately; they can double-click on the canvas to replace
    // it (no right-panel textarea anymore per Figma 2031:328975).
    text: "Default Text",
    fontFamily: "Pretendard",
    // Stored in 720-tall output reference coords; the editor preview
    // scales via 100cqh/720 → ~25 px displayed in the 352×626 canvas
    // (29 × 626/720 ≈ 25.2). Matches the host-subtitle 25 px target.
    fontSizePx: 29,
    fontWeight: 400,
    italic: false,
    underline: false,
    fontColor: "#000000",
    textAlign: "center",
    lineHeight: 1.3,
    letterSpacing: 0,
    highlightColor: null,
    highlightPaddingPx: 8,
    highlightOpacity: 1.0,
  };
}

// ---------------------------------------------------------------------------
// BackgroundOverlay default
// ---------------------------------------------------------------------------

const DEFAULT_BG_WIDTH_PX = 240;
const DEFAULT_BG_HEIGHT_PX = 80;

export function createDefaultBackgroundOverlay(args: {
  startMs: number;
  endMs?: number;
  layerIndex?: number;
  // ActionBar (figma 1602:40004 배경 섹션) 의 단색 배경 추가 버튼이
  // 색상 팔레트에서 고른 hex 를 전달한다. 미지정 시 기본값 #000000.
  fillColor?: string;
  // Image source — the "insert image" path reads a file as a data URL
  // and seeds it here so the new background overlay carries the image.
  imageUrl?: string;
}): EditorBackgroundOverlay {
  // Image inserts default to a larger canvas so the picked photo gets
  // an immediately visible footprint instead of being squeezed into the
  // 240×80 solid-color rectangle. Solid color inserts keep the legacy
  // dimensions so existing flows don't shift.
  const isImage = !!args.imageUrl;
  return {
    kind: "background",
    id: generateOverlayId("bg"),
    startMs: args.startMs,
    endMs: args.endMs ?? args.startMs + DEFAULT_OVERLAY_DURATION_MS,
    layerIndex: args.layerIndex ?? 0,
    transform: {
      ...DEFAULT_TRANSFORM,
      widthPx: isImage ? 480 : DEFAULT_BG_WIDTH_PX,
      heightPx: isImage ? 480 : DEFAULT_BG_HEIGHT_PX,
    },
    effects: { ...DEFAULT_EFFECTS },
    // Images render on top of a transparent fill by default so the
    // picture isn't tinted by an accidental black backing.
    fillColor: args.fillColor ?? (isImage ? "transparent" : "#000000"),
    imageUrl: args.imageUrl ?? null,
  };
}
