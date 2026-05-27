import type {
  CompositionPresetPayload,
  EditorOverlay,
  TransformProps,
  WireOverlay,
} from "./overlay-types";

// ============================================================================
// Playback State Machine (L8)
// ============================================================================

export type PlaybackRate = 1 | 2 | 4 | 8;

export type Playback =
  | { kind: "idle" }
  | { kind: "playing"; rate: PlaybackRate }
  | { kind: "paused"; pausedAtMs: number; resumeRate: PlaybackRate }
  | { kind: "seeking"; from: number; to: number; resume: Playback };

export type PlaybackEvent =
  | { kind: "TOGGLE" }
  | { kind: "PLAY_FORWARD" }
  | { kind: "PLAY_BACKWARD_OR_SLOW" }
  | { kind: "HARD_PAUSE" }
  | { kind: "SEEK"; toMs: number }
  | { kind: "SEEK_DONE" }
  | { kind: "REACHED_END" }
  | { kind: "SET_RATE"; rate: PlaybackRate };

export function nextRate(r: PlaybackRate): PlaybackRate {
  const table: Record<PlaybackRate, PlaybackRate> = { 1: 2, 2: 4, 4: 8, 8: 1 };
  return table[r];
}

export function prevRate(r: PlaybackRate): PlaybackRate {
  const table: Record<PlaybackRate, PlaybackRate> = { 8: 4, 4: 2, 2: 1, 1: 1 };
  return table[r];
}

// ============================================================================
// Shorts Editor Types
// ============================================================================

export interface EditorClip {
  id: string;
  sceneId: string;
  videoId: string;
  sourceType: string;
  originalStartMs: number;
  originalEndMs: number;
  trimStartMs: number;
  trimEndMs: number;
  timelineStartMs: number;
  volume: number;
  label?: string;
}

export interface SubtitleStyle {
  fontFamily: string;
  fontSizePx: number;
  fontColor: string;
  fontWeight: number;
  positionX: number;
  positionY: number;
  backgroundColor: string | null;
  backgroundOpacity: number;
}

export interface EditorSubtitle {
  id: string;
  text: string;
  startMs: number;
  endMs: number;
  style: SubtitleStyle;
}

export interface EditorState {
  videoId: string;
  sourceType: string;
  clips: EditorClip[];
  subtitles: EditorSubtitle[];
  // V2 overlays — coexist with V1 subtitles. Feature-flag selects which the
  // panel + preview consume; both can be non-empty mid-migration without
  // breaking validation. Backend serializer in composition-builder writes
  // both fields and lets the renderer ignore whichever is empty.
  overlays: EditorOverlay[];
  // Where the main <video> sits inside the preview canvas. The video
  // stays its own dedicated layer (not folded into ``overlays``), but
  // operators can drag and scale it like an overlay. Stored as a
  // normalized anchor in [0, 1] — 0.5/0.5 means the video centre
  // aligns with the canvas centre (the previous behaviour). The
  // renderer translates the <video> element by (x - 0.5, y - 0.5) so
  // 0.5/0.5 is a no-op. ``scale`` defaults to 1 so existing
  // compositions render identically until the operator resizes.
  //
  // ``outline`` is the operator-added border around the video frame
  // (윤곽선). CSS ``outline`` is preferred over ``border`` so the
  // outline doesn't shift the video element on width changes. ``null``
  // (or absent) means no outline; first colour pick from the panel
  // seeds widthPx to 5 px.
  videoTransform: {
    x: number;
    y: number;
    scale: number;
    // 2026-05-24 — rotation around the video's centre. Default 0 means
    // no rotation. Same [-360, 360] range used by overlay
    // TransformProps.rotationDeg so the same shift-snap UX applies.
    rotationDeg: number;
    outline?: { color: string; widthPx: number } | null;
    // 2026-05-24 — operator-added drop shadow rendered via CSS
    // ``filter: drop-shadow`` so it sits OUTSIDE the video frame
    // without affecting layout (parallels ``outline``). Mirrors
    // overlay EffectsProps.shadow so the BackgroundPanel can reuse
    // the existing shadow control row when the operator has the
    // video selected.
    shadow?: {
      color: string;
      offsetX: number;
      offsetY: number;
      blurPx: number;
      spreadPx: number;
    } | null;
  };
  // Unified z-order for video / letterbox / subtitles / overlays.
  // Array runs bottom → top; array index drives zIndex at render time.
  // Overlays are appended on add, stripped on remove; letterbox is
  // inserted/removed when state.letterbox transitions undefined↔defined.
  layerOrder: LayerOrderId[];
  // Optional global letterbox bars (Item 3 / D4 = B). Renders top and
  // bottom solid bars across the whole video duration. Stored as a
  // single field (NOT in the overlay array) because the spec is
  // "applies to the entire video, no per-time-range editing." Top/
  // bottom heights are percentages of the canvas; ``fillColor`` reuses
  // the single-background palette per D2. ``undefined`` means the
  // operator hasn't added letterboxing yet.
  //
  // Q4 — adds an optional outline (윤곽선) so the panel's stroke
  // controls can target the letterbox alongside inserted-image
  // overlays. ``borderColor === null`` means no outline; first colour
  // pick seeds ``borderWidthPx`` to 5 px per the Q4 default.
  letterbox?: {
    topHeightPct: number;
    bottomHeightPct: number;
    fillColor: string;
    borderColor: string | null;
    borderWidthPx: number;
  };
  selectedClipIndex: number | null;
  selectedSubtitleIndex: number | null;
  selectedOverlayId: string | null;
  // 2026-05-24 — selection-based routing model. The background panel's
  // existing controls (canvas align / layer order / 윤곽선) route to the
  // currently-selected element. ``selectedVideo`` / ``selectedLetterbox``
  // light up when the operator clicks the host video element or a
  // letterbox bar in the preview canvas. The five selection slots are
  // mutually exclusive — picking one clears the others (see SELECT_*
  // reducer cases for the mutex semantics).
  selectedVideo: boolean;
  selectedLetterbox: boolean;
  razorMode: boolean;
  playheadMs: number;
  playback: Playback;
  totalDurationMs: number;
  zoom: number;
  isDirty: boolean;
  // Undo stack for transform/length changes. Only drag-style gestures
  // push entries (move / resize / rotate / time-drag); text edits,
  // adds, deletes are out of scope. Bounded to 50 entries so a long
  // editor session doesn't grow the stack unboundedly.
  history: HistoryEntry[];
  // Redo stack — UNDO captures the pre-undo state of the entry's
  // target property here so REDO can re-apply it. Cleared whenever a
  // new gesture pushes onto ``history`` (standard undo/redo
  // semantics — a fresh edit invalidates the redo chain).
  redoHistory: HistoryEntry[];
  // Export range (L4 / T2). Operator marks in / out via I / O keys.
  // ``null`` means "use the whole composition" — composition-builder
  // collapses the range with ``inPointMs ?? 0`` and ``outPointMs ??
  // totalDurationMs``. Keeping them separate from playheadMs lets the
  // operator preview outside the range and still keep the marks.
  inPointMs: number | null;
  outPointMs: number | null;
}

// One slot in the unified z-order stack. ``overlay`` entries are keyed
// by overlay.id so removing an overlay also removes its slot.
export type LayerOrderId =
  | { kind: "video" }
  | { kind: "letterbox" }
  | { kind: "subtitles" }
  | { kind: "overlay"; id: string };

// One reversible drag-style gesture. The reducer pushes the
// pre-gesture state on pointerdown and pops + restores it when the
// operator hits Ctrl+Z / Cmd+Z.
// PR 5 follow-up (D5 = hybrid). Simple transforms (move / resize /
// rotate / time-drag) keep their inverse-action entries because the
// roll-back is a single property mutation — cheaper than snapshotting
// the whole reducer state every gesture. Complex actions (add /
// delete / text edit / trim / reorder / background swap) fall back to
// the catch-all ``snapshot`` variant: define an inverse for them is
// error-prone (text edits would need cursor-aware diff capture, add /
// delete need composite restoration of multiple slots, etc), so we
// simply restore the entire EditorState minus the history stacks.
//
// The two halves coexist on the same history stack — UNDO doesn't
// care which kind it pops, applyHistoryEntry switches on ``kind``.
export type HistoryEntry =
  | { kind: "subtitle_style"; index: number; style: SubtitleStyle }
  | { kind: "subtitle_time"; index: number; startMs: number; endMs: number }
  // overlay_time mirrors subtitle_time but for the overlay channel:
  // restores startMs/endMs on a single text overlay by id. Used by the
  // timeline trim handles (TextOverlayBlock) — overlay_transform alone
  // captures the transform vector, not the timing window.
  | { kind: "overlay_time"; id: string; startMs: number; endMs: number }
  | { kind: "overlay_transform"; id: string; transform: TransformProps }
  | { kind: "overlay_font_size"; id: string; fontSizePx: number }
  | { kind: "video_position"; x: number; y: number }
  | { kind: "video_scale"; scale: number }
  | { kind: "video_rotation"; rotationDeg: number }
  | {
      kind: "video_outline";
      outline: { color: string; widthPx: number } | null;
    }
  | {
      kind: "video_shadow";
      shadow: {
        color: string;
        offsetX: number;
        offsetY: number;
        blurPx: number;
        spreadPx: number;
      } | null;
    }
  | { kind: "letterbox"; letterbox: EditorState["letterbox"] }
  | { kind: "snapshot"; state: EditorState };

// ============================================================================
// Actions
// ============================================================================

export type EditorAction =
  | { type: "INIT_FROM_SCENES"; videoId: string; sourceType: string; clips: EditorClip[] }
  | { type: "INIT_FROM_COMPOSITION"; state: Partial<EditorState> }
  | { type: "ADD_CLIP"; clip: EditorClip }
  | { type: "REMOVE_CLIP"; index: number }
  | { type: "REORDER_CLIPS"; fromIndex: number; toIndex: number }
  | { type: "TRIM_CLIP"; index: number; trimStartMs?: number; trimEndMs?: number }
  | { type: "MOVE_CLIP"; index: number; timelineStartMs: number }
  | { type: "SET_CLIP_VOLUME"; index: number; volume: number }
  | { type: "SELECT_CLIP"; index: number | null }
  | { type: "ADD_SUBTITLE"; subtitle: EditorSubtitle }
  | { type: "UPDATE_SUBTITLE"; index: number; updates: Partial<Omit<EditorSubtitle, "id">> }
  | { type: "UPDATE_ALL_SUBTITLE_STYLES"; updates: Partial<SubtitleStyle> }
  | { type: "REMOVE_SUBTITLE"; index: number }
  | { type: "SELECT_SUBTITLE"; index: number | null }
  // V2 overlay actions (text + background).
  | { type: "ADD_OVERLAY"; overlay: EditorOverlay }
  | { type: "UPDATE_OVERLAY"; id: string; updates: Partial<EditorOverlay> }
  | { type: "REMOVE_OVERLAY"; id: string }
  | { type: "SELECT_OVERLAY"; id: string | null }
  | { type: "REORDER_OVERLAY"; id: string; direction: "front" | "back" | "forward" | "backward" }
  // 2026-05-24 — selection-based routing actions. ``active=true`` selects
  // the slot and clears every other selection slot (mutual exclusion).
  // ``active=false`` clears the slot without touching the others.
  | { type: "SELECT_VIDEO"; active: boolean }
  | { type: "SELECT_LETTERBOX"; active: boolean }
  | { type: "UPDATE_VIDEO_POSITION"; x: number; y: number }
  | { type: "UPDATE_VIDEO_SCALE"; scale: number }
  | { type: "UPDATE_VIDEO_ROTATION"; rotationDeg: number }
  | {
      type: "SET_VIDEO_OUTLINE";
      outline: { color: string; widthPx: number } | null;
    }
  | {
      type: "SET_VIDEO_SHADOW";
      shadow: {
        color: string;
        offsetX: number;
        offsetY: number;
        blurPx: number;
        spreadPx: number;
      } | null;
    }
  | { type: "REORDER_LAYER"; layer: LayerOrderId; direction: "front" | "back" | "forward" | "backward" }
  | { type: "SET_LETTERBOX"; letterbox: EditorState["letterbox"] }
  | { type: "SET_PLAYHEAD"; ms: number }
  | { type: "PLAYBACK_EVENT"; event: PlaybackEvent }
  | { type: "SET_ZOOM"; zoom: number }
  // L4 / T2 export range. ``ms === null`` clears the mark.
  | { type: "SET_IN_POINT"; ms: number | null }
  | { type: "SET_OUT_POINT"; ms: number | null }
  // L5 / T5 split/razor. atMs is in timeline coords; reducer no-ops if
  // the target's timing window doesn't actually straddle atMs (e.g.
  // playhead is past the subtitle's endMs).
  | { type: "SET_RAZOR_MODE"; active: boolean }
  | { type: "SPLIT_SUBTITLE"; index: number; atMs: number }
  | { type: "SPLIT_OVERLAY"; id: string; atMs: number }
  | { type: "SPLIT_CLIP"; index: number; atMs: number }
  | { type: "MARK_CLEAN" }
  // Apply a composition template snapshot at the current playhead.
  // Reducer behaviour (operator-confirmed 2026-05-24):
  //   * subtitleStyle → merge into every existing subtitle.style
  //   * overlays      → append (new id each, shift timing to playhead)
  //   * letterbox     → SET when non-null, else leave existing
  //   * videoTransform→ SET (overwrite)
  // The caller is expected to wrap the dispatch in a pushSnapshot so
  // a single Ctrl+Z reverts the whole apply.
  | { type: "APPLY_COMPOSITION_TEMPLATE"; payload: CompositionPresetPayload }
  | { type: "PUSH_HISTORY"; entry: HistoryEntry }
  | { type: "UNDO" }
  | { type: "REDO" };

// ============================================================================
// CompositionSpec output types (matches backend schema)
// ============================================================================

export interface CompositionOutputSpec {
  width: number;
  height: number;
  fps: number;
  format: "mp4" | "webm";
  background_color: string;
}

export interface CompositionSceneClip {
  scene_id: string;
  video_id: string;
  source_type: string;
  start_ms: number;
  end_ms: number;
  timeline_start_ms: number;
  volume: number;
  crop_x: number;
  crop_y: number;
  crop_w: number;
  crop_h: number;
}

export interface CompositionSubtitleStyle {
  font_family: string;
  font_size_px: number;
  font_color: string;
  font_weight: number;
  position_x: number;
  position_y: number;
  background_color: string | null;
  background_opacity: number;
}

export interface CompositionSubtitle {
  text: string;
  start_ms: number;
  end_ms: number;
  style: CompositionSubtitleStyle;
}

// Render-fidelity: unified z-order sent to the backend so the worker
// composites layers in the operator's chosen order. Absent → worker
// uses its own hard-coded order (video, letterbox, subtitles, overlays).
export interface CompositionLayerOrder {
  kind: "video" | "letterbox" | "subtitles" | "overlay";
  id?: string;
}

// Render-fidelity: letterbox bar spec. The backend draws solid color
// bars + optional inner-edge border stroke before compositing
// subtitles and overlays.
export interface CompositionLetterbox {
  top_height_pct: number;
  bottom_height_pct: number;
  fill_color: string;
  border_color: string | null;
  border_width_px: number;
}

// Render-fidelity: video placement on the 9:16 canvas. Normalized
// anchor (0.5/0.5 = centered) + uniform scale + optional rotation,
// outline, and drop-shadow that the editor preview also applies.
// Older compositions persisted without these fields → the renderer
// treats them as defaults (no rotation, no border, no shadow).
export interface CompositionVideoTransform {
  x: number;
  y: number;
  scale: number;
  rotation_deg?: number;
  outline?: { color: string; width_px: number } | null;
  shadow?: {
    color: string;
    offset_x: number;
    offset_y: number;
    blur_px: number;
    spread_px: number;
  } | null;
}

export interface CompositionSpec {
  output: CompositionOutputSpec;
  scene_clips: CompositionSceneClip[];
  subtitles: CompositionSubtitle[];
  // V2 overlays — empty for V1-only compositions; populated by the new editor.
  // The wire shape lives in overlay-types.ts.
  overlays: WireOverlay[];
  transitions: unknown[];
  title: string | null;
  version: number;
  // Render-fidelity fields — optional so older compositions still parse.
  layer_order?: CompositionLayerOrder[];
  letterbox?: CompositionLetterbox;
  video_transform?: CompositionVideoTransform;
}
