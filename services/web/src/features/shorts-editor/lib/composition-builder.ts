import type { EditorState, CompositionSpec, CompositionLayerOrder, CompositionLetterbox, CompositionVideoTransform } from "./types";

/**
 * Normalise a colour string into the hex form the backend validator
 * accepts (``#RRGGBB`` or ``#RRGGBBAA``). The editor stores the CSS
 * keyword ``"transparent"`` for image-backed background overlays and
 * for ColorPalette "off" picks; the renderer's contracts validator
 * rejects anything that isn't hex, so convert here at the wire boundary.
 *
 * Anything that already starts with ``#`` is passed through verbatim
 * (we don't try to validate the hex digits — the backend does that and
 * the operator sees a precise message via formatErrorDetail).
 */
function normaliseWireHex(color: string): string {
  if (color === "transparent") return "#00000000";
  return color;
}
import type {
  EditorBackgroundOverlay,
  EditorTextOverlay,
  WireBackgroundOverlay,
  WireOverlay,
  WireTextOverlay,
} from "./overlay-types";
import { DEFAULT_OUTPUT } from "../constants";

/**
 * Build a CompositionSpec dict from the editor state.
 * Mirrors the highlight_reel service's build_composition_dict() pattern.
 *
 * L4 / T2 — when state.inPointMs / outPointMs are set, the spec is
 * cropped to that range before serialization:
 *   * scene_clips outside the range are dropped; partial clips are
 *     trimmed at the source level (adjust trim_start / trim_end so
 *     the backend never sees frames it shouldn't render).
 *   * subtitles and overlays outside the range are dropped; partial
 *     ones are clamped to the range edges.
 *   * Every remaining timeline coord is shifted by -inPointMs so the
 *     export starts at t=0.
 *
 * The wire schema is intentionally unchanged — the backend just sees
 * a shorter, time-zeroed composition. No backend coordination needed.
 */
export function buildCompositionSpec(
  state: EditorState,
  title?: string | null,
): CompositionSpec {
  const inPoint = state.inPointMs ?? 0;
  const outPoint = state.outPointMs ?? state.totalDurationMs;
  // No range set (or range covers the whole clip) → fast path, no cropping.
  const hasRange =
    state.inPointMs != null || state.outPointMs != null;

  const clips = hasRange ? cropClips(state.clips, inPoint, outPoint) : state.clips;
  const subtitles = hasRange
    ? cropTimeRanges(state.subtitles, inPoint, outPoint)
    : state.subtitles;
  const overlays = hasRange
    ? cropTimeRanges(state.overlays, inPoint, outPoint)
    : state.overlays;

  // Render-fidelity: serialize layer_order so the worker composites
  // in the operator's chosen z-order.
  const layer_order: CompositionLayerOrder[] = state.layerOrder.map((l) => {
    if (l.kind === "overlay") return { kind: "overlay" as const, id: l.id };
    return { kind: l.kind };
  });

  // Render-fidelity: serialize letterbox when present.
  const letterbox: CompositionLetterbox | undefined = state.letterbox
    ? {
        top_height_pct: state.letterbox.topHeightPct,
        bottom_height_pct: state.letterbox.bottomHeightPct,
        fill_color: normaliseWireHex(state.letterbox.fillColor),
        border_color:
          state.letterbox.borderColor != null
            ? normaliseWireHex(state.letterbox.borderColor)
            : null,
        border_width_px: state.letterbox.borderWidthPx,
      }
    : undefined;

  // Render-fidelity: serialize video transform when non-default.
  // ``isDefaultTransform`` now accounts for rotation, outline, and
  // shadow too — a video at the centre with default scale but a
  // non-null outline still needs to round-trip through the backend
  // worker, so the spec must carry the fields.
  const vt = state.videoTransform;
  const hasOutline =
    vt.outline != null && vt.outline.widthPx > 0;
  const hasShadow = vt.shadow != null;
  const isDefaultTransform =
    vt.x === 0.5 &&
    vt.y === 0.5 &&
    vt.scale === 1 &&
    (vt.rotationDeg ?? 0) === 0 &&
    !hasOutline &&
    !hasShadow;
  const video_transform: CompositionVideoTransform | undefined = isDefaultTransform
    ? undefined
    : {
        x: vt.x,
        y: vt.y,
        scale: vt.scale,
        rotation_deg: vt.rotationDeg ?? 0,
        outline: hasOutline && vt.outline
          ? { color: vt.outline.color, width_px: vt.outline.widthPx }
          : null,
        shadow: hasShadow && vt.shadow
          ? {
              color: vt.shadow.color,
              offset_x: vt.shadow.offsetX,
              offset_y: vt.shadow.offsetY,
              blur_px: vt.shadow.blurPx,
              spread_px: vt.shadow.spreadPx,
            }
          : null,
      };

  return {
    output: { ...DEFAULT_OUTPUT },
    scene_clips: clips.map((clip) => ({
      scene_id: clip.sceneId,
      video_id: clip.videoId,
      source_type: clip.sourceType,
      start_ms: clip.trimStartMs,
      end_ms: clip.trimEndMs,
      timeline_start_ms: clip.timelineStartMs,
      volume: clip.volume,
      crop_x: 0.0,
      crop_y: 0.0,
      crop_w: 1.0,
      crop_h: 1.0,
    })),
    subtitles: subtitles.map((sub) => ({
      text: sub.text,
      start_ms: sub.startMs,
      end_ms: sub.endMs,
      style: {
        font_family: sub.style.fontFamily,
        font_size_px: sub.style.fontSizePx,
        font_color: sub.style.fontColor,
        font_weight: sub.style.fontWeight,
        position_x: sub.style.positionX,
        position_y: sub.style.positionY,
        background_color: sub.style.backgroundColor,
        background_opacity: sub.style.backgroundOpacity,
      },
    })),
    overlays: overlays.map(serializeOverlay),
    transitions: [],
    title: title ?? null,
    version: 1,
    layer_order,
    ...(letterbox && { letterbox }),
    ...(video_transform && { video_transform }),
  };
}

// ---------------------------------------------------------------------------
// Export range cropping helpers (L4 / T2)
// ---------------------------------------------------------------------------

function cropClips(
  clips: EditorState["clips"],
  inPoint: number,
  outPoint: number,
): EditorState["clips"] {
  const out: EditorState["clips"] = [];
  for (const clip of clips) {
    const clipStart = clip.timelineStartMs;
    const clipEnd = clipStart + (clip.trimEndMs - clip.trimStartMs);
    if (clipEnd <= inPoint || clipStart >= outPoint) continue; // fully out

    const leadingClip = Math.max(0, inPoint - clipStart);
    const trailingClip = Math.max(0, clipEnd - outPoint);
    out.push({
      ...clip,
      trimStartMs: clip.trimStartMs + leadingClip,
      trimEndMs: clip.trimEndMs - trailingClip,
      timelineStartMs: Math.max(0, clipStart - inPoint),
    });
  }
  return out;
}

function cropTimeRanges<T extends { startMs: number; endMs: number }>(
  items: T[],
  inPoint: number,
  outPoint: number,
): T[] {
  const out: T[] = [];
  for (const item of items) {
    if (item.endMs <= inPoint || item.startMs >= outPoint) continue;
    out.push({
      ...item,
      startMs: Math.max(0, item.startMs - inPoint),
      endMs: Math.min(item.endMs, outPoint) - inPoint,
    });
  }
  return out;
}

// ---------------------------------------------------------------------------
// V2 overlay serialization (camelCase → snake_case wire format)
// ---------------------------------------------------------------------------

function serializeOverlay(overlay: EditorTextOverlay | EditorBackgroundOverlay): WireOverlay {
  if (overlay.kind === "text") {
    return serializeTextOverlay(overlay);
  }
  return serializeBackgroundOverlay(overlay);
}

function serializeTextOverlay(o: EditorTextOverlay): WireTextOverlay {
  return {
    kind: "text",
    id: o.id,
    start_ms: o.startMs,
    end_ms: o.endMs,
    layer_index: o.layerIndex,
    transform: {
      x: o.transform.x,
      y: o.transform.y,
      rotation_deg: o.transform.rotationDeg,
      width_px: o.transform.widthPx,
      height_px: o.transform.heightPx,
    },
    effects: {
      opacity: o.effects.opacity,
      stroke: o.effects.stroke
        ? { color: o.effects.stroke.color, width_px: o.effects.stroke.widthPx }
        : null,
      shadow: o.effects.shadow
        ? {
            color: o.effects.shadow.color,
            offset_x: o.effects.shadow.offsetX,
            offset_y: o.effects.shadow.offsetY,
            blur_px: o.effects.shadow.blurPx,
            spread_px: o.effects.shadow.spreadPx,
          }
        : null,
    },
    text: o.text,
    font_family: o.fontFamily,
    font_size_px: o.fontSizePx,
    font_weight: o.fontWeight,
    italic: o.italic,
    underline: o.underline,
    font_color: o.fontColor,
    text_align: o.textAlign,
    line_height: o.lineHeight,
    letter_spacing: o.letterSpacing,
    highlight_color: o.highlightColor,
    highlight_padding_px: o.highlightPaddingPx,
    highlight_opacity: o.highlightOpacity,
  };
}

function serializeBackgroundOverlay(o: EditorBackgroundOverlay): WireBackgroundOverlay {
  return {
    kind: "background",
    id: o.id,
    start_ms: o.startMs,
    end_ms: o.endMs,
    layer_index: o.layerIndex,
    transform: {
      x: o.transform.x,
      y: o.transform.y,
      rotation_deg: o.transform.rotationDeg,
      width_px: o.transform.widthPx,
      height_px: o.transform.heightPx,
    },
    effects: {
      opacity: o.effects.opacity,
      stroke: o.effects.stroke
        ? { color: o.effects.stroke.color, width_px: o.effects.stroke.widthPx }
        : null,
      shadow: o.effects.shadow
        ? {
            color: o.effects.shadow.color,
            offset_x: o.effects.shadow.offsetX,
            offset_y: o.effects.shadow.offsetY,
            blur_px: o.effects.shadow.blurPx,
            spread_px: o.effects.shadow.spreadPx,
          }
        : null,
    },
    fill_color: normaliseWireHex(o.fillColor),
  };
}
