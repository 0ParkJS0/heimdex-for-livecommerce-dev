// ============================================================================
// Wire → Editor subtitle/overlay converters
//
// The backend's CompositionSpec keeps subtitles in snake_case wire shape
// (`{ text, start_ms, end_ms, style: { font_family, font_size_px, ... } }`).
// The editor's reducer state uses camelCase EditorSubtitle (V1) and
// EditorTextOverlay (V2) — these helpers do the field mapping in one
// place so hydration sites stay readable and style fidelity (stroke,
// shadow, highlight pill) survives the round trip.
// ============================================================================

import { DEFAULT_SUBTITLE_STYLE } from "../constants";
import {
  DEFAULT_EFFECTS,
  DEFAULT_TRANSFORM,
  generateOverlayId,
} from "./overlay-defaults";
import type {
  EditorBackgroundOverlay,
  EditorTextOverlay,
  EffectsProps,
  ShadowProps,
  StrokeProps,
  TransformProps,
} from "./overlay-types";
import type { EditorSubtitle, SubtitleStyle } from "./types";

/** Loose wire shape — matches what `GET /shorts/{id}/composition` returns. */
export interface WireSubtitleStyle {
  font_family?: string;
  font_size_px?: number;
  font_color?: string;
  font_weight?: number;
  position_x?: number;
  position_y?: number;
  background_color?: string | null;
  background_opacity?: number;
  background_padding?: number;
  // V2-style nested effects, present when the cue came from the V2
  // composition_builder. Old auto-shorts cues only carry the flat
  // background_* fields above.
  stroke?: {
    color?: string;
    width_px?: number;
  } | null;
  shadow?: {
    color?: string;
    offset_x?: number;
    offset_y?: number;
    blur_px?: number;
    spread_px?: number;
  } | null;
}

export interface WireSubtitle {
  text: string;
  start_ms: number;
  end_ms: number;
  style?: WireSubtitleStyle | null;
}

/**
 * Convert a wire-format subtitle into the V1 EditorSubtitle reducer
 * shape. The flat `background_color` field maps to the legacy V1
 * `backgroundColor` (the pill itself); stroke/shadow have no V1
 * counterpart and are dropped.
 */
export function wireSubtitleToEditorSubtitle(
  wire: WireSubtitle,
): EditorSubtitle {
  const wireStyle = wire.style ?? {};
  const style: SubtitleStyle = {
    fontFamily: wireStyle.font_family ?? DEFAULT_SUBTITLE_STYLE.fontFamily,
    fontSizePx: wireStyle.font_size_px ?? DEFAULT_SUBTITLE_STYLE.fontSizePx,
    fontColor: wireStyle.font_color ?? DEFAULT_SUBTITLE_STYLE.fontColor,
    fontWeight: wireStyle.font_weight ?? DEFAULT_SUBTITLE_STYLE.fontWeight,
    positionX: wireStyle.position_x ?? DEFAULT_SUBTITLE_STYLE.positionX,
    positionY: wireStyle.position_y ?? DEFAULT_SUBTITLE_STYLE.positionY,
    backgroundColor:
      wireStyle.background_color ?? DEFAULT_SUBTITLE_STYLE.backgroundColor,
    backgroundOpacity:
      wireStyle.background_opacity ?? DEFAULT_SUBTITLE_STYLE.backgroundOpacity,
  };
  return {
    id: generateLoadedSubtitleId(),
    text: wire.text,
    startMs: wire.start_ms,
    endMs: wire.end_ms,
    style,
  };
}

/**
 * Convert a wire-format subtitle into a V2 EditorTextOverlay. The
 * flat `background_*` fields land on the V2 `highlight*` (text-fitted
 * pill) keys; nested stroke/shadow propagate to `effects`.
 *
 * Callers should pass the result through the editor's
 * `addOverlayDirect` so the reducer keeps its layer-index bookkeeping
 * (each new overlay lands on top of the existing stack).
 */
export function wireSubtitleToEditorTextOverlay(
  wire: WireSubtitle,
): EditorTextOverlay {
  const wireStyle = wire.style ?? {};
  const transform: TransformProps = {
    ...DEFAULT_TRANSFORM,
    x: wireStyle.position_x ?? 0.5,
    y: wireStyle.position_y ?? DEFAULT_TRANSFORM.y,
  };
  const stroke: StrokeProps | null = wireStyle.stroke
    ? {
        color: wireStyle.stroke.color ?? "#000000",
        widthPx: wireStyle.stroke.width_px ?? 0,
      }
    : null;
  const shadow: ShadowProps | null = wireStyle.shadow
    ? {
        color: wireStyle.shadow.color ?? "#000000",
        offsetX: wireStyle.shadow.offset_x ?? 0,
        offsetY: wireStyle.shadow.offset_y ?? 0,
        blurPx: wireStyle.shadow.blur_px ?? 0,
        spreadPx: wireStyle.shadow.spread_px ?? 0,
      }
    : null;
  const effects: EffectsProps = {
    ...DEFAULT_EFFECTS,
    stroke,
    shadow,
  };
  return {
    kind: "text",
    id: generateOverlayId("text"),
    startMs: wire.start_ms,
    endMs: wire.end_ms,
    layerIndex: 0, // reducer overwrites with maxLayer + 1 on add
    transform,
    effects,
    text: wire.text,
    fontFamily: wireStyle.font_family ?? "Pretendard",
    fontSizePx: wireStyle.font_size_px ?? 32,
    fontWeight: wireStyle.font_weight ?? 700,
    italic: false,
    underline: false,
    fontColor: wireStyle.font_color ?? "#000000",
    textAlign: "center",
    lineHeight: 1.3,
    letterSpacing: 0,
    // Auto-shorts pill style maps to highlight on V2 — keep it visible
    // in the editor even though the legacy cue used `background_color`.
    highlightColor: wireStyle.background_color ?? null,
    highlightPaddingPx: wireStyle.background_padding ?? 8,
    highlightOpacity: wireStyle.background_opacity ?? 1.0,
  };
}

let _loadedSubtitleCounter = 0;
function generateLoadedSubtitleId(): string {
  return `sub_loaded_${Date.now()}_${++_loadedSubtitleCounter}`;
}

// Re-export for callers that want to satisfy `EditorBackgroundOverlay`
// payloads alongside the text overlay path (currently unused but kept
// here so future extensions don't drift apart).
export type { EditorBackgroundOverlay };
