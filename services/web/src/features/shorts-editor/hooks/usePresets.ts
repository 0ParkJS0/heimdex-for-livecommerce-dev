"use client";

/**
 * usePresets — backend-backed preset list with optimistic save/delete.
 *
 * Loads on mount, exposes save/rename/delete/applyTo. Errors surface as
 * `error: string | null` for callers to render; the hook does not throw.
 *
 * Tolerant of the API not existing yet (404 / network error during the
 * grace period before PR #90 lands): logs and renders an empty list.
 */

import { useCallback, useEffect, useState } from "react";

import {
  createPreset as apiCreate,
  deletePreset as apiDelete,
  listPresets as apiList,
  PresetRateLimitError,
  updatePreset as apiUpdate,
} from "@/lib/api/subtitle-presets";
import type {
  CompositionPresetPayload,
  EditorBackgroundOverlay,
  EditorOverlay,
  EditorTextOverlay,
  PresetKind,
  WirePreset,
} from "../lib/overlay-types";
import type { EditorState } from "../lib/types";

type TokenGetter = () => Promise<string | null>;

interface UsePresetsArgs {
  kind?: PresetKind;
  getToken: TokenGetter;
  enabled?: boolean; // skip network when false (e.g. flag off)
}

export interface PresetsApi {
  presets: WirePreset[];
  isLoading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  save: (
    name: string,
    overlay: EditorOverlay,
    isShared: boolean,
  ) => Promise<WirePreset | null>;
  // Composition presets — snapshot the global editor chrome (subtitle
  // style, overlay set, letterbox, video transform). Backend already
  // accepts kind="composition" with a generic style_json dict.
  saveComposition: (
    name: string,
    payload: CompositionPresetPayload,
    isShared: boolean,
  ) => Promise<WirePreset | null>;
  rename: (presetId: string, name: string) => Promise<void>;
  setShared: (presetId: string, isShared: boolean) => Promise<void>;
  remove: (presetId: string) => Promise<void>;
  applyTo: <O extends EditorOverlay>(
    overlay: O,
    preset: WirePreset,
  ) => O;
  // Re-parse a preset's style_json into a CompositionPresetPayload
  // ready for the APPLY_COMPOSITION_TEMPLATE reducer action. Returns
  // null when the preset's kind is not "composition".
  parseComposition: (preset: WirePreset) => CompositionPresetPayload | null;
}

export function usePresets({
  kind,
  getToken,
  enabled = true,
}: UsePresetsArgs): PresetsApi {
  const [presets, setPresets] = useState<WirePreset[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!enabled) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiList({ kind, limit: 100, offset: 0 }, getToken);
      setPresets(res.items);
    } catch (err) {
      // Endpoint may not be deployed yet (PR #90 in flight). Log + degrade
      // to empty rather than blocking the panel from rendering.
      // eslint-disable-next-line no-console
      console.warn("usePresets.reload failed", err);
      setError(err instanceof Error ? err.message : "프리셋을 불러올 수 없습니다.");
      setPresets([]);
    } finally {
      setIsLoading(false);
    }
  }, [enabled, kind, getToken]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const save = useCallback(
    async (name: string, overlay: EditorOverlay, isShared: boolean) => {
      try {
        const styleJson = extractStyleFragment(overlay);
        const created = await apiCreate(
          {
            name,
            kind: overlay.kind,
            style_json: styleJson,
            is_shared: isShared,
          },
          getToken,
        );
        // Prepend so the latest preset shows at the top of the dropdown.
        setPresets((prev) => [created, ...prev]);
        return created;
      } catch (err) {
        if (err instanceof PresetRateLimitError) {
          setError(err.message);
        } else {
          setError(err instanceof Error ? err.message : "프리셋 저장 실패");
        }
        return null;
      }
    },
    [getToken],
  );

  // Composition save — serialises the payload as snake_case JSON so
  // the backend can store it under WirePreset.style_json verbatim,
  // then prepends the returned preset to the list so the operator
  // sees it immediately in the templates grid.
  const saveComposition = useCallback(
    async (
      name: string,
      payload: CompositionPresetPayload,
      isShared: boolean,
    ) => {
      try {
        const styleJson = serializeCompositionPayload(payload);
        const created = await apiCreate(
          {
            name,
            kind: "composition",
            style_json: styleJson,
            is_shared: isShared,
          },
          getToken,
        );
        setPresets((prev) => [created, ...prev]);
        return created;
      } catch (err) {
        if (err instanceof PresetRateLimitError) {
          setError(err.message);
        } else {
          setError(err instanceof Error ? err.message : "프리셋 저장 실패");
        }
        return null;
      }
    },
    [getToken],
  );

  const parseComposition = useCallback(
    (preset: WirePreset): CompositionPresetPayload | null => {
      if (preset.kind !== "composition") return null;
      return parseCompositionPayload(preset.style_json);
    },
    [],
  );

  const rename = useCallback(
    async (presetId: string, name: string) => {
      try {
        const updated = await apiUpdate(presetId, { name }, getToken);
        setPresets((prev) => prev.map((p) => (p.id === presetId ? updated : p)));
      } catch (err) {
        setError(err instanceof Error ? err.message : "이름 변경 실패");
      }
    },
    [getToken],
  );

  const setShared = useCallback(
    async (presetId: string, isShared: boolean) => {
      try {
        const updated = await apiUpdate(
          presetId,
          { is_shared: isShared },
          getToken,
        );
        setPresets((prev) => prev.map((p) => (p.id === presetId ? updated : p)));
      } catch (err) {
        setError(err instanceof Error ? err.message : "공유 변경 실패");
      }
    },
    [getToken],
  );

  const remove = useCallback(
    async (presetId: string) => {
      // Optimistic removal — the API returns 204 on success and we won't
      // need the row back. On failure, refetch.
      const previous = presets;
      setPresets((prev) => prev.filter((p) => p.id !== presetId));
      try {
        await apiDelete(presetId, getToken);
      } catch (err) {
        setError(err instanceof Error ? err.message : "프리셋 삭제 실패");
        setPresets(previous);
      }
    },
    [getToken, presets],
  );

  const applyTo = useCallback(
    <O extends EditorOverlay>(overlay: O, preset: WirePreset): O => {
      // Apply preset = merge style fields, preserve identity (id, kind,
      // start/end, layer_index, transform). Preset.style_json was stripped
      // of identity at write time by services/api/.../subtitle_presets/schemas.py.
      const styleFields = preset.style_json as Record<string, unknown>;
      return mergeStyleFragment(overlay, styleFields);
    },
    [],
  );

  return {
    presets,
    isLoading,
    error,
    reload,
    save,
    saveComposition,
    rename,
    setShared,
    remove,
    applyTo,
    parseComposition,
  };
}

// ---------------------------------------------------------------------------
// Style fragment extract / merge (camelCase domain ↔ snake_case wire)
// ---------------------------------------------------------------------------

/**
 * Extract the *style* slice of an overlay (no identity, no timing, no
 * position) in wire format. The API performs the same shape validation
 * server-side via _validate_style_json.
 */
function extractStyleFragment(overlay: EditorOverlay): Record<string, unknown> {
  if (overlay.kind === "text") {
    return extractTextStyle(overlay);
  }
  return extractBackgroundStyle(overlay);
}

function extractTextStyle(o: EditorTextOverlay): Record<string, unknown> {
  return {
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
    effects: serializeEffects(o.effects),
  };
}

function extractBackgroundStyle(
  o: EditorBackgroundOverlay,
): Record<string, unknown> {
  return {
    fill_color: o.fillColor,
    effects: serializeEffects(o.effects),
  };
}

function serializeEffects(
  e: EditorOverlay["effects"],
): Record<string, unknown> {
  return {
    opacity: e.opacity,
    stroke: e.stroke
      ? { color: e.stroke.color, width_px: e.stroke.widthPx }
      : null,
    shadow: e.shadow
      ? {
          color: e.shadow.color,
          offset_x: e.shadow.offsetX,
          offset_y: e.shadow.offsetY,
          blur_px: e.shadow.blurPx,
          spread_px: e.shadow.spreadPx,
        }
      : null,
  };
}

function mergeStyleFragment<O extends EditorOverlay>(
  overlay: O,
  style: Record<string, unknown>,
): O {
  if (overlay.kind === "text") {
    return mergeTextStyle(overlay, style) as O;
  }
  return mergeBackgroundStyle(
    overlay as EditorBackgroundOverlay,
    style,
  ) as O;
}

function mergeTextStyle(
  base: EditorTextOverlay,
  style: Record<string, unknown>,
): EditorTextOverlay {
  return {
    ...base,
    text: getString(style, "text", base.text),
    fontFamily: getString(style, "font_family", base.fontFamily) as
      | "Pretendard"
      | "Noto Sans KR",
    fontSizePx: getNumber(style, "font_size_px", base.fontSizePx),
    fontWeight: getNumber(style, "font_weight", base.fontWeight),
    italic: getBool(style, "italic", base.italic),
    underline: getBool(style, "underline", base.underline),
    fontColor: getString(style, "font_color", base.fontColor),
    textAlign: (getString(style, "text_align", base.textAlign) as
      | "left"
      | "center"
      | "right"),
    lineHeight: getNumber(style, "line_height", base.lineHeight),
    letterSpacing: getNumber(style, "letter_spacing", base.letterSpacing),
    highlightColor:
      style["highlight_color"] === null
        ? null
        : getString(style, "highlight_color", base.highlightColor ?? "") || null,
    highlightPaddingPx: getNumber(
      style,
      "highlight_padding_px",
      base.highlightPaddingPx,
    ),
    highlightOpacity: getNumber(
      style,
      "highlight_opacity",
      base.highlightOpacity,
    ),
    effects: parseEffects(style["effects"], base.effects),
  };
}

function mergeBackgroundStyle(
  base: EditorBackgroundOverlay,
  style: Record<string, unknown>,
): EditorBackgroundOverlay {
  return {
    ...base,
    fillColor: getString(style, "fill_color", base.fillColor),
    effects: parseEffects(style["effects"], base.effects),
  };
}

function parseEffects(
  raw: unknown,
  fallback: EditorOverlay["effects"],
): EditorOverlay["effects"] {
  if (!raw || typeof raw !== "object") return fallback;
  const e = raw as Record<string, unknown>;
  const stroke = e["stroke"] as Record<string, unknown> | null | undefined;
  const shadow = e["shadow"] as Record<string, unknown> | null | undefined;
  return {
    opacity: typeof e["opacity"] === "number" ? e["opacity"] : fallback.opacity,
    stroke: stroke
      ? {
          color: typeof stroke["color"] === "string" ? stroke["color"] : "#000000",
          widthPx: typeof stroke["width_px"] === "number" ? stroke["width_px"] : 1,
        }
      : null,
    shadow: shadow
      ? {
          color: typeof shadow["color"] === "string" ? shadow["color"] : "#000000",
          offsetX: typeof shadow["offset_x"] === "number" ? shadow["offset_x"] : 0,
          offsetY: typeof shadow["offset_y"] === "number" ? shadow["offset_y"] : 4,
          blurPx: typeof shadow["blur_px"] === "number" ? shadow["blur_px"] : 0,
          spreadPx:
            typeof shadow["spread_px"] === "number" ? shadow["spread_px"] : 0,
        }
      : null,
  };
}

function getString(
  obj: Record<string, unknown>,
  key: string,
  fallback: string,
): string {
  const v = obj[key];
  return typeof v === "string" ? v : fallback;
}

function getNumber(
  obj: Record<string, unknown>,
  key: string,
  fallback: number,
): number {
  const v = obj[key];
  return typeof v === "number" ? v : fallback;
}

function getBool(
  obj: Record<string, unknown>,
  key: string,
  fallback: boolean,
): boolean {
  const v = obj[key];
  return typeof v === "boolean" ? v : fallback;
}

// ---------------------------------------------------------------------------
// Composition preset (de)serialisation
// ---------------------------------------------------------------------------
//
// The wire format for kind="composition" is a single dict under
// WirePreset.style_json with snake_case top-level keys mirroring the
// CompositionPresetPayload shape. Overlay bodies are also serialised
// in snake_case so a saved preset round-trips cleanly through the
// backend's _validate_style_json (which only enforces "the JSON is an
// object").

/**
 * Build a CompositionPresetPayload from the current editor state.
 * Used by the GNB save flow (handleTemplateSave with mode="composition").
 *
 * Operator-confirmed shape (2026-05-24):
 *   * subtitleStyle  → state.subtitles[0]?.style (operator only edits a
 *                      single global style)
 *   * overlays       → every operator-added overlay, stripped of id +
 *                      absolute timing (duration retained)
 *   * letterbox      → state.letterbox or null
 *   * videoTransform → state.videoTransform
 */
export function buildCompositionPayloadFromState(
  state: EditorState,
): CompositionPresetPayload {
  const firstSub = state.subtitles[0];
  const subtitleStyle = firstSub
    ? {
        fontFamily: firstSub.style.fontFamily,
        fontSizePx: firstSub.style.fontSizePx,
        fontColor: firstSub.style.fontColor,
        fontWeight: firstSub.style.fontWeight,
        positionX: firstSub.style.positionX,
        positionY: firstSub.style.positionY,
        backgroundColor: firstSub.style.backgroundColor,
        backgroundOpacity: firstSub.style.backgroundOpacity,
      }
    : null;

  const overlays = state.overlays.map((o) => {
    const durationMs = Math.max(1, o.endMs - o.startMs);
    // Strip startMs / endMs / kind from the payload — the apply
    // reducer regenerates id, kind is carried in the outer
    // CompositionPresetOverlayPayload.kind, and timing is anchored to
    // the apply-time playhead. The original ``id`` is kept on the
    // preset overlay (NOT inside ``payload``) so the saved layerOrder
    // can reference it and the apply reducer can rewrite it to the
    // freshly-issued overlay id.
    if (o.kind === "text") {
      const {
        id: _id,
        kind: _kind,
        startMs: _s,
        endMs: _e,
        layerIndex: _li,
        ...rest
      } = o;
      void _id;
      void _kind;
      void _s;
      void _e;
      void _li;
      return {
        kind: "text" as const,
        id: o.id,
        layerIndex: o.layerIndex,
        durationMs,
        payload: rest as unknown as Record<string, unknown>,
      };
    }
    const {
      id: _id,
      kind: _kind,
      startMs: _s,
      endMs: _e,
      layerIndex: _li,
      ...rest
    } = o;
    void _id;
    void _kind;
    void _s;
    void _e;
    void _li;
    return {
      kind: "background" as const,
      id: o.id,
      layerIndex: o.layerIndex,
      durationMs,
      payload: rest as unknown as Record<string, unknown>,
    };
  });

  const letterbox = state.letterbox
    ? {
        topHeightPct: state.letterbox.topHeightPct,
        bottomHeightPct: state.letterbox.bottomHeightPct,
        fillColor: state.letterbox.fillColor,
        borderColor: state.letterbox.borderColor,
        borderWidthPx: state.letterbox.borderWidthPx,
      }
    : null;

  return {
    subtitleStyle,
    overlays,
    letterbox,
    videoTransform: {
      x: state.videoTransform.x,
      y: state.videoTransform.y,
      scale: state.videoTransform.scale,
      rotationDeg: state.videoTransform.rotationDeg ?? 0,
      outline: state.videoTransform.outline ?? null,
      shadow: state.videoTransform.shadow ?? null,
    },
    // Stack order snapshot. Overlay slot ids reference the preset's
    // own overlay ids (saved on each overlays[i].id above), so the
    // apply reducer can rewrite them to the freshly issued ids of the
    // appended overlays.
    layerOrder: state.layerOrder.map((l) =>
      l.kind === "overlay" ? { kind: "overlay" as const, id: l.id } : { kind: l.kind },
    ),
  };
}

function serializeCompositionPayload(
  payload: CompositionPresetPayload,
): Record<string, unknown> {
  return {
    subtitle_style: payload.subtitleStyle
      ? {
          font_family: payload.subtitleStyle.fontFamily,
          font_size_px: payload.subtitleStyle.fontSizePx,
          font_color: payload.subtitleStyle.fontColor,
          font_weight: payload.subtitleStyle.fontWeight,
          position_x: payload.subtitleStyle.positionX,
          position_y: payload.subtitleStyle.positionY,
          background_color: payload.subtitleStyle.backgroundColor,
          background_opacity: payload.subtitleStyle.backgroundOpacity,
        }
      : null,
    overlays: payload.overlays.map((o) => ({
      kind: o.kind,
      id: o.id,
      layer_index: o.layerIndex,
      duration_ms: o.durationMs,
      payload: o.payload,
    })),
    layer_order: payload.layerOrder?.map((l) =>
      l.kind === "overlay" ? { kind: "overlay", id: l.id } : { kind: l.kind },
    ),
    letterbox: payload.letterbox
      ? {
          top_height_pct: payload.letterbox.topHeightPct,
          bottom_height_pct: payload.letterbox.bottomHeightPct,
          fill_color: payload.letterbox.fillColor,
          border_color: payload.letterbox.borderColor,
          border_width_px: payload.letterbox.borderWidthPx,
        }
      : null,
    video_transform: {
      x: payload.videoTransform.x,
      y: payload.videoTransform.y,
      scale: payload.videoTransform.scale,
      rotation_deg: payload.videoTransform.rotationDeg ?? 0,
      outline: payload.videoTransform.outline
        ? {
            color: payload.videoTransform.outline.color,
            width_px: payload.videoTransform.outline.widthPx,
          }
        : null,
      shadow: payload.videoTransform.shadow
        ? {
            color: payload.videoTransform.shadow.color,
            offset_x: payload.videoTransform.shadow.offsetX,
            offset_y: payload.videoTransform.shadow.offsetY,
            blur_px: payload.videoTransform.shadow.blurPx,
            spread_px: payload.videoTransform.shadow.spreadPx,
          }
        : null,
    },
  };
}

function parseCompositionPayload(
  raw: Record<string, unknown>,
): CompositionPresetPayload {
  // Subtitle style — every numeric field defaults reasonable so a
  // malformed dict still produces an applicable payload.
  const subRaw = raw["subtitle_style"];
  const subtitleStyle =
    subRaw && typeof subRaw === "object"
      ? (() => {
          const s = subRaw as Record<string, unknown>;
          return {
            fontFamily: getString(s, "font_family", "Pretendard"),
            fontSizePx: getNumber(s, "font_size_px", 29),
            fontColor: getString(s, "font_color", "#000000"),
            fontWeight: getNumber(s, "font_weight", 700),
            positionX: getNumber(s, "position_x", 0.5),
            positionY: getNumber(s, "position_y", 0.8),
            backgroundColor:
              s["background_color"] === null
                ? null
                : getString(s, "background_color", "#FFFFFF") || null,
            backgroundOpacity: getNumber(s, "background_opacity", 0.95),
          };
        })()
      : null;

  // Overlays — each entry carries its kind + layerIndex + durationMs +
  // payload (the overlay body sans id/timing). Skip malformed entries
  // so a partial wire dump still produces a usable apply.
  const overlaysRaw = Array.isArray(raw["overlays"]) ? raw["overlays"] : [];
  const overlays = overlaysRaw
    .map((entry) => {
      if (!entry || typeof entry !== "object") return null;
      const e = entry as Record<string, unknown>;
      const kind = e["kind"];
      if (kind !== "text" && kind !== "background") return null;
      const body = e["payload"];
      if (!body || typeof body !== "object") return null;
      const idRaw = e["id"];
      const id = typeof idRaw === "string" ? idRaw : undefined;
      return {
        kind,
        ...(id ? { id } : {}),
        layerIndex: getNumber(e, "layer_index", 0),
        durationMs: getNumber(e, "duration_ms", 3000),
        payload: body as Record<string, unknown>,
      };
    })
    .filter(
      (v): v is CompositionPresetPayload["overlays"][number] => v !== null,
    );

  // Layer order — optional. Each entry is ``{ kind, id? }`` (snake-case
  // ``layer_order`` on the wire). Overlay-kind entries carry the
  // preset-time id which the apply reducer rewrites to the new
  // overlay id. Skip malformed entries so a partial wire dump still
  // applies cleanly. Returns ``undefined`` when missing so the apply
  // reducer can fall back to existing layerOrder.
  const layerOrderRaw = Array.isArray(raw["layer_order"])
    ? raw["layer_order"]
    : null;
  const layerOrder = layerOrderRaw
    ? (layerOrderRaw
        .map((entry) => {
          if (!entry || typeof entry !== "object") return null;
          const l = entry as Record<string, unknown>;
          const kind = l["kind"];
          if (kind === "overlay") {
            const idRaw = l["id"];
            if (typeof idRaw !== "string") return null;
            return { kind: "overlay" as const, id: idRaw };
          }
          if (kind === "video" || kind === "letterbox" || kind === "subtitles") {
            return { kind };
          }
          return null;
        })
        .filter(
          (v): v is NonNullable<CompositionPresetPayload["layerOrder"]>[number] =>
            v !== null,
        ))
    : undefined;

  // Letterbox — keep null when the raw value is null/missing so the
  // reducer leaves the current letterbox unchanged on apply.
  const lbRaw = raw["letterbox"];
  const letterbox =
    lbRaw && typeof lbRaw === "object"
      ? (() => {
          const l = lbRaw as Record<string, unknown>;
          return {
            topHeightPct: getNumber(l, "top_height_pct", 0),
            bottomHeightPct: getNumber(l, "bottom_height_pct", 0),
            fillColor: getString(l, "fill_color", "#000000"),
            borderColor:
              l["border_color"] === null
                ? null
                : getString(l, "border_color", "#000000") || null,
            borderWidthPx: getNumber(l, "border_width_px", 0),
          };
        })()
      : null;

  // Video transform — always present, defaults to centred 1× so a
  // legacy preset without the field still applies cleanly. ``outline``
  // rides along on the same payload; ``null`` / missing → no outline.
  const vtRaw = raw["video_transform"];
  const videoTransform =
    vtRaw && typeof vtRaw === "object"
      ? (() => {
          const v = vtRaw as Record<string, unknown>;
          const outlineRaw = v["outline"];
          const outline =
            outlineRaw && typeof outlineRaw === "object"
              ? (() => {
                  const o = outlineRaw as Record<string, unknown>;
                  return {
                    color: getString(o, "color", "#000000"),
                    widthPx: getNumber(o, "width_px", 0),
                  };
                })()
              : null;
          const shadowRaw = v["shadow"];
          const shadow =
            shadowRaw && typeof shadowRaw === "object"
              ? (() => {
                  const s = shadowRaw as Record<string, unknown>;
                  return {
                    color: getString(s, "color", "#000000"),
                    offsetX: getNumber(s, "offset_x", 0),
                    offsetY: getNumber(s, "offset_y", 4),
                    blurPx: getNumber(s, "blur_px", 0),
                    spreadPx: getNumber(s, "spread_px", 0),
                  };
                })()
              : null;
          return {
            x: getNumber(v, "x", 0.5),
            y: getNumber(v, "y", 0.5),
            scale: getNumber(v, "scale", 1),
            rotationDeg: getNumber(v, "rotation_deg", 0),
            outline,
            shadow,
          };
        })()
      : {
          x: 0.5,
          y: 0.5,
          scale: 1,
          rotationDeg: 0,
          outline: null,
          shadow: null,
        };

  return {
    subtitleStyle,
    overlays,
    letterbox,
    videoTransform,
    ...(layerOrder ? { layerOrder } : {}),
  };
}
