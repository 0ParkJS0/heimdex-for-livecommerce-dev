import { useReducer, useCallback, useRef } from "react";
import type {
  EditorState,
  EditorAction,
  EditorClip,
  EditorSubtitle,
  SubtitleStyle,
  HistoryEntry,
  LayerOrderId,
  Playback,
  PlaybackEvent,
  PlaybackRate,
} from "../lib/types";
import { nextRate, prevRate } from "../lib/types";
import type { EditorOverlay } from "../lib/overlay-types";
import {
  createDefaultBackgroundOverlay,
  createDefaultTextOverlay,
  DEFAULT_OVERLAY_DURATION_MS,
  generateOverlayId,
} from "../lib/overlay-defaults";
import type { StarterTemplateStyle } from "../lib/starter-templates";
import { recomputeTimeline, getTotalDuration } from "../lib/timeline-math";
import {
  splitSubtitleText,
  splitSubtitlesAtMs,
  splitClipsAtMs,
} from "../lib/clip-subtitle-link";
import { DEFAULT_OUTPUT, DEFAULT_ZOOM, DEFAULT_SUBTITLE_STYLE, DEFAULT_SUBTITLE_DURATION_MS } from "../constants";
import { parseSpeakerTranscript } from "@/lib/speaker-transcript";

const INITIAL_STATE: EditorState = {
  videoId: "",
  sourceType: "gdrive",
  clips: [],
  subtitles: [],
  overlays: [],
  videoTransform: {
    x: 0.5,
    y: 0.5,
    scale: 1,
    rotationDeg: 0,
    outline: null,
    shadow: null,
  },
  layerOrder: [{ kind: "video" }, { kind: "subtitles" }],
  selectedClipIndex: null,
  selectedSubtitleIndex: null,
  selectedOverlayId: null,
  // 2026-05-24 — selection-based routing model. ``selectedVideo`` and
  // ``selectedLetterbox`` light up when the operator clicks the host
  // video element or a letterbox bar in the preview canvas; the
  // background panel's existing 화면정렬 / 레이어순서 / 윤곽선 controls
  // route by which slot is active.
  selectedVideo: false,
  selectedLetterbox: false,
  razorMode: false,
  playheadMs: 0,
  playback: { kind: "idle" },
  totalDurationMs: 0,
  zoom: DEFAULT_ZOOM,
  isDirty: false,
  history: [],
  redoHistory: [],
  // No marks set yet — composition-builder treats null as "use whole clip".
  inPointMs: null,
  outPointMs: null,
};

const HISTORY_LIMIT = 50;

function clampVolume(v: number): number {
  return Math.max(0, Math.min(3, v));
}

// Build a canonical layerOrder from overlays + letterbox presence.
//
// Stack policy (operator request 2026-05-25):
//   bottom → top
//   1) video
//   2) letterbox (when present)
//   3) background overlays (sorted by layerIndex)
//   4) subtitles  ← always above any background
//   5) text overlays (sorted by layerIndex)  ← always at the very top
//
// Subtitles and text overlays must never be hidden behind a background
// the operator just dropped on the canvas. ``REORDER_LAYER`` enforces
// the same invariant by rejecting any move that would put a non-text
// slot above the subtitles slot (see the case below).
function buildLayerOrder(
  overlays: EditorOverlay[],
  hasLetterbox: boolean,
): LayerOrderId[] {
  const base: LayerOrderId[] = [{ kind: "video" }];
  if (hasLetterbox) base.push({ kind: "letterbox" });
  const bgSorted = overlays
    .filter((o) => o.kind === "background")
    .sort((a, b) => a.layerIndex - b.layerIndex);
  for (const o of bgSorted) {
    base.push({ kind: "overlay", id: o.id });
  }
  base.push({ kind: "subtitles" });
  const textSorted = overlays
    .filter((o) => o.kind === "text")
    .sort((a, b) => a.layerIndex - b.layerIndex);
  for (const o of textSorted) {
    base.push({ kind: "overlay", id: o.id });
  }
  return base;
}

// Re-sort a layerOrder so it respects buildLayerOrder's policy without
// dropping any slot the caller already had. Used by mutators that
// touch layerOrder directly (ADD_OVERLAY, REORDER_LAYER, APPLY_*)
// where simply rebuilding from scratch would discard valid state.
function normalizeLayerOrder(
  layerOrder: LayerOrderId[],
  overlays: EditorOverlay[],
): LayerOrderId[] {
  const kindOf = new Map(overlays.map((o) => [o.id, o.kind] as const));
  const out: LayerOrderId[] = [];
  // 1) video — exactly one (insert if missing).
  out.push({ kind: "video" });
  // 2) letterbox — keep iff present in input.
  if (layerOrder.some((l) => l.kind === "letterbox")) {
    out.push({ kind: "letterbox" });
  }
  // 3) backgrounds — preserve their original relative order.
  for (const l of layerOrder) {
    if (l.kind === "overlay" && kindOf.get(l.id) === "background") {
      out.push({ kind: "overlay", id: l.id });
    }
  }
  // 4) subtitles — exactly one.
  out.push({ kind: "subtitles" });
  // 5) text overlays — preserve their original relative order.
  for (const l of layerOrder) {
    if (l.kind === "overlay" && kindOf.get(l.id) === "text") {
      out.push({ kind: "overlay", id: l.id });
    }
  }
  return out;
}

function layerOrderIdMatches(a: LayerOrderId, b: LayerOrderId): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === "overlay" && b.kind === "overlay") return a.id === b.id;
  return true;
}

// L8 — playback state machine. Pure function, no side effects.
// Exported for unit testing (playback-state-machine.test.ts).
export function reducePlayback(
  pb: Playback,
  event: PlaybackEvent,
  playheadMs: number,
  totalDurationMs: number,
): Playback {
  switch (pb.kind) {
    case "idle": {
      switch (event.kind) {
        case "TOGGLE":
          return { kind: "playing", rate: 1 };
        case "PLAY_FORWARD":
          return { kind: "playing", rate: 1 };
        case "PLAY_BACKWARD_OR_SLOW": {
          // jog -1s, stay idle — caller reads playheadMs from state
          return pb;
        }
        case "HARD_PAUSE":
          return pb;
        case "SEEK":
          return { kind: "seeking", from: 0, to: event.toMs, resume: { kind: "idle" } };
        case "SEEK_DONE":
          return pb;
        case "REACHED_END":
          return pb;
        case "SET_RATE":
          return pb;
      }
      break;
    }
    case "playing": {
      switch (event.kind) {
        case "TOGGLE":
          return { kind: "paused", pausedAtMs: playheadMs, resumeRate: pb.rate };
        case "PLAY_FORWARD":
          return { kind: "playing", rate: nextRate(pb.rate) };
        case "PLAY_BACKWARD_OR_SLOW":
          if (pb.rate > 1) return { kind: "playing", rate: prevRate(pb.rate) };
          // rate=1: pause and jog -1s
          return { kind: "paused", pausedAtMs: Math.max(0, playheadMs - 1000), resumeRate: 1 };
        case "HARD_PAUSE":
          return { kind: "paused", pausedAtMs: playheadMs, resumeRate: 1 };
        case "SEEK":
          return { kind: "seeking", from: playheadMs, to: event.toMs, resume: { kind: "playing", rate: pb.rate } };
        case "SEEK_DONE":
          return pb;
        case "REACHED_END":
          return { kind: "paused", pausedAtMs: totalDurationMs, resumeRate: pb.rate };
        case "SET_RATE":
          return { kind: "playing", rate: event.rate };
      }
      break;
    }
    case "paused": {
      switch (event.kind) {
        case "TOGGLE":
          return { kind: "playing", rate: pb.resumeRate };
        case "PLAY_FORWARD":
          return { kind: "playing", rate: 1 };
        case "PLAY_BACKWARD_OR_SLOW":
          // jog -1s, stay paused
          return pb;
        case "HARD_PAUSE":
          return pb;
        case "SEEK":
          return { kind: "seeking", from: pb.pausedAtMs, to: event.toMs, resume: { kind: "paused", pausedAtMs: event.toMs, resumeRate: pb.resumeRate } };
        case "SEEK_DONE":
          return pb;
        case "REACHED_END":
          return pb;
        case "SET_RATE":
          return { kind: "paused", pausedAtMs: pb.pausedAtMs, resumeRate: event.rate };
      }
      break;
    }
    case "seeking": {
      switch (event.kind) {
        case "TOGGLE":
        case "PLAY_FORWARD":
        case "PLAY_BACKWARD_OR_SLOW":
        case "HARD_PAUSE":
        case "SET_RATE":
          return pb;
        case "SEEK":
          // coalesce: keep from, update to
          return { kind: "seeking", from: pb.from, to: event.toMs, resume: pb.resume };
        case "SEEK_DONE": {
          // resume with playheadMs = to
          const r = pb.resume;
          if (r.kind === "paused") return { ...r, pausedAtMs: pb.to };
          return r;
        }
        case "REACHED_END":
          return { kind: "paused", pausedAtMs: totalDurationMs, resumeRate: 1 };
      }
      break;
    }
  }
}

function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "INIT_FROM_SCENES": {
      const clips = recomputeTimeline(action.clips);
      return {
        ...INITIAL_STATE,
        videoId: action.videoId,
        sourceType: action.sourceType,
        clips,
        totalDurationMs: getTotalDuration(clips),
      };
    }

    case "INIT_FROM_COMPOSITION": {
      const merged = { ...INITIAL_STATE, ...action.state };
      // Hydrate scale + outline defaults so saved compositions without
      // those fields render identically to their pre-scale / pre-outline
      // state.
      const incomingVt = merged.videoTransform as {
        x: number;
        y: number;
        scale?: number;
        rotationDeg?: number;
        outline?: { color: string; widthPx: number } | null;
        shadow?: {
          color: string;
          offsetX: number;
          offsetY: number;
          blurPx: number;
          spreadPx: number;
        } | null;
      };
      const videoTransform = {
        x: incomingVt.x,
        y: incomingVt.y,
        scale: incomingVt.scale ?? 1,
        rotationDeg: incomingVt.rotationDeg ?? 0,
        outline: incomingVt.outline ?? null,
        shadow: incomingVt.shadow ?? null,
      };
      // Rebuild layerOrder from scratch to guarantee consistency with
      // the hydrated overlays/letterbox, regardless of what was persisted.
      const layerOrder = buildLayerOrder(
        merged.overlays,
        merged.letterbox != null,
      );
      const clips = recomputeTimeline(merged.clips);
      return {
        ...merged,
        videoTransform,
        layerOrder,
        clips,
        totalDurationMs: getTotalDuration(clips),
        isDirty: false,
      };
    }

    case "ADD_CLIP": {
      const clips = recomputeTimeline([...state.clips, action.clip]);
      return {
        ...state,
        clips,
        totalDurationMs: getTotalDuration(clips),
        isDirty: true,
      };
    }

    case "REMOVE_CLIP": {
      if (action.index < 0 || action.index >= state.clips.length) return state;
      // Remove the clip but do NOT recompute timeline or shift
      // downstream clips/subtitles — gaps are allowed.
      const clips = state.clips.filter((_, i) => i !== action.index);
      let newSelected = state.selectedClipIndex;
      if (newSelected != null) {
        if (newSelected === action.index) newSelected = null;
        else if (newSelected > action.index) newSelected -= 1;
      }
      return {
        ...state,
        clips,
        totalDurationMs: getTotalDuration(clips),
        selectedClipIndex: newSelected,
        isDirty: true,
      };
    }

    case "REORDER_CLIPS": {
      const { fromIndex, toIndex } = action;
      if (
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= state.clips.length ||
        toIndex >= state.clips.length ||
        fromIndex === toIndex
      ) {
        return state;
      }
      const next = [...state.clips];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      // Swap timelineStartMs between the moved clip and the displaced
      // clip so their visual positions exchange. No full recompute —
      // gaps are preserved.
      return {
        ...state,
        clips: next,
        totalDurationMs: getTotalDuration(next),
        selectedClipIndex: toIndex,
        isDirty: true,
      };
    }

    case "TRIM_CLIP": {
      const { index, trimStartMs, trimEndMs } = action;
      if (index < 0 || index >= state.clips.length) return state;
      const clip = state.clips[index];
      const newStart = trimStartMs != null
        ? Math.max(clip.originalStartMs, Math.min(trimStartMs, clip.trimEndMs - 1))
        : clip.trimStartMs;
      const newEnd = trimEndMs != null
        ? Math.min(clip.originalEndMs, Math.max(trimEndMs, newStart + 1))
        : clip.trimEndMs;
      // When the start handle is trimmed, the clip's timelineStartMs
      // shifts so the visible portion stays anchored at the same visual
      // position on the timeline. When the end handle is trimmed, only
      // trimEndMs changes — timelineStartMs is unaffected.
      const startDelta = newStart - clip.trimStartMs;
      const newTimelineStart = clip.timelineStartMs + startDelta;
      // Update only the trimmed clip — no cascading recompute so gaps
      // are preserved and downstream clips stay in place.
      const clips = state.clips.map((c, i) =>
        i === index
          ? { ...c, trimStartMs: newStart, trimEndMs: newEnd, timelineStartMs: newTimelineStart }
          : c,
      );
      // Subtitles are NOT mutated — render-time filtering via
      // getVisibleSubtitles hides out-of-range subtitles; extending
      // the trim back restores them.
      return {
        ...state,
        clips,
        totalDurationMs: getTotalDuration(clips),
        isDirty: true,
      };
    }

    case "MOVE_CLIP": {
      if (action.index < 0 || action.index >= state.clips.length) return state;
      const target = state.clips[action.index];
      const oldStart = target.timelineStartMs;
      const newStart = Math.max(0, action.timelineStartMs);
      const delta = newStart - oldStart;
      if (delta === 0) return state;
      const clipDuration = target.trimEndMs - target.trimStartMs;
      const oldEnd = oldStart + clipDuration;
      // Move the clip + every subtitle / text-overlay that lives
      // inside its OLD window by the same delta so the operator's
      // mental model "subtitle is glued to the scene" holds (frame-
      // level link). Items outside the window stay put — they belong
      // to other clips or to no clip at all.
      const clips = state.clips.map((c, i) =>
        i === action.index ? { ...c, timelineStartMs: newStart } : c,
      );
      const subtitles = state.subtitles.map((s) => {
        const within = s.startMs >= oldStart && s.endMs <= oldEnd;
        return within
          ? { ...s, startMs: s.startMs + delta, endMs: s.endMs + delta }
          : s;
      });
      const overlays = state.overlays.map((o) => {
        const within = o.startMs >= oldStart && o.endMs <= oldEnd;
        return within
          ? { ...o, startMs: o.startMs + delta, endMs: o.endMs + delta }
          : o;
      });
      return {
        ...state,
        clips,
        subtitles,
        overlays,
        totalDurationMs: getTotalDuration(clips),
        isDirty: true,
      };
    }

    case "SET_CLIP_VOLUME": {
      if (action.index < 0 || action.index >= state.clips.length) return state;
      const clips = state.clips.map((c, i) =>
        i === action.index ? { ...c, volume: clampVolume(action.volume) } : c,
      );
      return { ...state, clips, isDirty: true };
    }

    case "SELECT_CLIP":
      return {
        ...state,
        selectedClipIndex: action.index,
        // Mutual exclusion — picking a clip clears every other selection
        // slot so the right-panel controls have an unambiguous target.
        selectedSubtitleIndex: action.index != null ? null : state.selectedSubtitleIndex,
        selectedOverlayId: action.index != null ? null : state.selectedOverlayId,
        selectedVideo: action.index != null ? false : state.selectedVideo,
        selectedLetterbox: action.index != null ? false : state.selectedLetterbox,
      };

    case "ADD_SUBTITLE": {
      return {
        ...state,
        subtitles: [...state.subtitles, action.subtitle],
        isDirty: true,
      };
    }

    case "UPDATE_SUBTITLE": {
      if (action.index < 0 || action.index >= state.subtitles.length) return state;
      const subtitles = state.subtitles.map((s, i) =>
        i === action.index ? { ...s, ...action.updates } : s,
      );
      return { ...state, subtitles, isDirty: true };
    }

    case "UPDATE_ALL_SUBTITLE_STYLES": {
      if (state.subtitles.length === 0) return state;
      const subtitles = state.subtitles.map((s) => ({
        ...s,
        style: { ...s.style, ...action.updates },
      }));
      return { ...state, subtitles, isDirty: true };
    }

    case "REMOVE_SUBTITLE": {
      if (action.index < 0 || action.index >= state.subtitles.length) return state;
      let newSelected = state.selectedSubtitleIndex;
      if (newSelected != null) {
        if (newSelected === action.index) newSelected = null;
        else if (newSelected > action.index) newSelected -= 1;
      }
      // Removing a subtitle no longer affects clips — gaps are allowed
      // and clips keep their positions independently.
      return {
        ...state,
        subtitles: state.subtitles.filter((_, i) => i !== action.index),
        selectedSubtitleIndex: newSelected,
        isDirty: true,
      };
    }

    case "SELECT_SUBTITLE":
      return {
        ...state,
        selectedSubtitleIndex: action.index,
        selectedClipIndex: action.index != null ? null : state.selectedClipIndex,
        selectedOverlayId: action.index != null ? null : state.selectedOverlayId,
        selectedVideo: action.index != null ? false : state.selectedVideo,
        selectedLetterbox: action.index != null ? false : state.selectedLetterbox,
      };

    case "ADD_OVERLAY": {
      // Layer policy:
      //   - background overlays go to the BOTTOM (layerIndex 0; existing
      //     overlays shift up by 1) so a freshly-added background sits
      //     behind the video + everything else, acting as the canvas
      //     filler for landscape video centered on the 9:16 canvas.
      //   - non-background (text/image) overlays still land at the
      //     FRONT so the operator sees their new annotation on top of
      //     prior content. Caller can REORDER_OVERLAY afterward.
      const isBackground = action.overlay.kind === "background";
      let overlays: EditorOverlay[];
      let positioned: EditorOverlay;
      if (isBackground) {
        const shifted = state.overlays.map((o) => ({
          ...o,
          layerIndex: o.layerIndex + 1,
        }));
        positioned = { ...action.overlay, layerIndex: 0 };
        overlays = [...shifted, positioned];
      } else {
        const maxLayer = state.overlays.reduce(
          (m, o) => Math.max(m, o.layerIndex),
          -1,
        );
        positioned = { ...action.overlay, layerIndex: maxLayer + 1 };
        overlays = [...state.overlays, positioned];
      }
      // Densely repack layerIndex 0..N-1 so there are no gaps after a
      // background-add shift (mirrors REORDER_OVERLAY's post-splice
      // repack). Without this, the first text overlay would keep
      // layerIndex 1 after a background insert, leaving a hole at 0
      // that confuses downstream assertions and the reorder logic.
      const sorted = [...overlays].sort((a, b) => a.layerIndex - b.layerIndex);
      overlays = sorted.map((o, i) => ({ ...o, layerIndex: i }));
      // Append the new overlay slot, then normalise. The normaliser
      // routes background overlays under the subtitles slot and text
      // overlays above it so subtitles + text are guaranteed to stay
      // on top of any newly-added background (operator policy 2026-05-25).
      const layerOrder = normalizeLayerOrder(
        [...state.layerOrder, { kind: "overlay", id: positioned.id }],
        overlays,
      );
      return {
        ...state,
        overlays,
        layerOrder,
        selectedOverlayId: positioned.id,
        // Selecting a new overlay clears clip + subtitle selection so the
        // panel switches to overlay-edit mode. Also clears the
        // video/letterbox selection slots so the background-panel
        // controls stay in sync with the new overlay-selected state
        // (selection-based routing model — 2026-05-24).
        selectedClipIndex: null,
        selectedSubtitleIndex: null,
        selectedVideo: false,
        selectedLetterbox: false,
        isDirty: true,
      };
    }

    case "UPDATE_OVERLAY": {
      const overlays = state.overlays.map((o) =>
        o.id === action.id
          // Spread is type-safe because each overlay variant's discriminator
          // (`kind`) can't be changed via UPDATE_OVERLAY — the schema rules
          // it out by validation, but TS sees it as Partial<EditorOverlay>
          // so we cast the merge result to the original variant.
          ? ({ ...o, ...action.updates } as EditorOverlay)
          : o,
      );
      return { ...state, overlays, isDirty: true };
    }

    case "REMOVE_OVERLAY": {
      const overlays = state.overlays.filter((o) => o.id !== action.id);
      const layerOrder = state.layerOrder.filter(
        (l) => !(l.kind === "overlay" && l.id === action.id),
      );
      return {
        ...state,
        overlays,
        layerOrder,
        selectedOverlayId:
          state.selectedOverlayId === action.id ? null : state.selectedOverlayId,
        isDirty: true,
      };
    }

    case "SELECT_OVERLAY":
      return {
        ...state,
        selectedOverlayId: action.id,
        selectedClipIndex: action.id != null ? null : state.selectedClipIndex,
        selectedSubtitleIndex: action.id != null ? null : state.selectedSubtitleIndex,
        selectedVideo: action.id != null ? false : state.selectedVideo,
        selectedLetterbox: action.id != null ? false : state.selectedLetterbox,
      };

    case "SELECT_VIDEO":
      return {
        ...state,
        selectedVideo: action.active,
        // Mutual exclusion — selecting the video clears every other
        // selection slot. ``active=false`` only clears the video slot.
        selectedClipIndex: action.active ? null : state.selectedClipIndex,
        selectedSubtitleIndex: action.active ? null : state.selectedSubtitleIndex,
        selectedOverlayId: action.active ? null : state.selectedOverlayId,
        selectedLetterbox: action.active ? false : state.selectedLetterbox,
      };

    case "SELECT_LETTERBOX":
      return {
        ...state,
        selectedLetterbox: action.active,
        selectedClipIndex: action.active ? null : state.selectedClipIndex,
        selectedSubtitleIndex: action.active ? null : state.selectedSubtitleIndex,
        selectedOverlayId: action.active ? null : state.selectedOverlayId,
        selectedVideo: action.active ? false : state.selectedVideo,
      };

    case "REORDER_OVERLAY": {
      const idx = state.overlays.findIndex((o) => o.id === action.id);
      if (idx < 0) return state;
      // Per-overlay reorder. layerIndex doubles as the timeline row
      // index and the preview-stack zIndex. We mutate ONLY the
      // dragged overlay's layerIndex so dropping into an empty row
      // works (no swap target required). Multiple overlays may share
      // a layerIndex (they overlap visually in the timeline row).
      // MAX_TEXT_OVERLAY_LAYER caps the row at 2 rows total (0, 1)
      // — operator policy 2026-05-24: '텍스트용 row는 최대 2개로
      // 줄여줘, drag 시 새로운 row를 신설하지 않음'. forward beyond
      // the cap → no-op.
      const MAX_TEXT_OVERLAY_LAYER = 1;
      const current = state.overlays[idx];
      const maxLayer = state.overlays.reduce(
        (acc, o) => Math.max(acc, o.layerIndex),
        0,
      );
      let nextLayer = current.layerIndex;
      switch (action.direction) {
        case "back":
          nextLayer = 0;
          break;
        case "front":
          nextLayer = Math.min(MAX_TEXT_OVERLAY_LAYER, maxLayer + 1);
          break;
        case "backward":
          nextLayer = Math.max(0, current.layerIndex - 1);
          break;
        case "forward":
          nextLayer = Math.min(MAX_TEXT_OVERLAY_LAYER, current.layerIndex + 1);
          break;
      }
      if (nextLayer === current.layerIndex) return state;
      const overlays = state.overlays.map((o) =>
        o.id === action.id ? { ...o, layerIndex: nextLayer } : o,
      );
      return { ...state, overlays, isDirty: true };
    }

    case "REORDER_LAYER": {
      const { layer, direction } = action;
      // 2026-05-25 — subtitles + text-overlay slots are pinned to the
      // top of the stack (above any background overlay) and may not be
      // reordered. Reject those attempts up front so the popover's
      // dispatch is a silent no-op even if the UI's disabled guard is
      // bypassed.
      if (layer.kind === "subtitles") return state;
      if (layer.kind === "overlay") {
        const overlay = state.overlays.find((o) => o.id === layer.id);
        if (overlay && overlay.kind === "text") return state;
      }
      const idx = state.layerOrder.findIndex((l) => layerOrderIdMatches(l, layer));
      if (idx < 0) return state;
      const next = [...state.layerOrder];
      let targetIdx = idx;
      switch (direction) {
        case "back":
          targetIdx = 0;
          break;
        case "front":
          targetIdx = next.length - 1;
          break;
        case "backward":
          targetIdx = Math.max(0, idx - 1);
          break;
        case "forward":
          targetIdx = Math.min(next.length - 1, idx + 1);
          break;
      }
      if (targetIdx === idx) return state;
      const [moved] = next.splice(idx, 1);
      next.splice(targetIdx, 0, moved);
      // Renormalise so a reorder that would otherwise push a background
      // overlay above the subtitles slot snaps back into the segment
      // boundaries (background → subtitles → text). Within-segment
      // ordering is preserved by normaliseLayerOrder.
      const normalised = normalizeLayerOrder(next, state.overlays);
      return { ...state, layerOrder: normalised, isDirty: true };
    }

    case "UPDATE_VIDEO_POSITION": {
      const x = Math.max(0, Math.min(1, action.x));
      const y = Math.max(0, Math.min(1, action.y));
      return {
        ...state,
        videoTransform: { ...state.videoTransform, x, y },
        isDirty: true,
      };
    }

    case "UPDATE_VIDEO_SCALE": {
      const scale = Math.max(0.1, Math.min(10, action.scale));
      return {
        ...state,
        videoTransform: { ...state.videoTransform, scale },
        isDirty: true,
      };
    }

    case "UPDATE_VIDEO_ROTATION": {
      // Clamp to the same [-360, 360] range used by overlay rotation
      // so the shift-snap UX (every 90°) lands on the same multiples.
      const rotationDeg = Math.max(-360, Math.min(360, action.rotationDeg));
      return {
        ...state,
        videoTransform: { ...state.videoTransform, rotationDeg },
        isDirty: true,
      };
    }

    case "SET_VIDEO_SHADOW": {
      // ``null`` clears the shadow. Numeric ranges mirror the overlay
      // ShadowProps clamps: offsetX/offsetY in [-100, 100], blurPx in
      // [0, 200], spreadPx in [0, 100] (see overlay-types.ts).
      const shadow =
        action.shadow === null
          ? null
          : {
              color: action.shadow.color,
              offsetX: Math.max(-100, Math.min(100, action.shadow.offsetX)),
              offsetY: Math.max(-100, Math.min(100, action.shadow.offsetY)),
              blurPx: Math.max(0, Math.min(200, action.shadow.blurPx)),
              spreadPx: Math.max(0, Math.min(100, action.shadow.spreadPx)),
            };
      return {
        ...state,
        videoTransform: { ...state.videoTransform, shadow },
        isDirty: true,
      };
    }

    case "SET_VIDEO_OUTLINE": {
      // Outline is the operator-added border around the video frame.
      // ``null`` clears it. Width is clamped to [0, 50] matching the
      // existing 굵기 step range used by overlay strokes + letterbox
      // border. We keep the outline object alive at width=0 so the
      // operator can dial back up without losing their colour pick —
      // explicit ``null`` is the "remove" signal.
      const outline =
        action.outline === null
          ? null
          : {
              color: action.outline.color,
              widthPx: Math.max(0, Math.min(50, action.outline.widthPx)),
            };
      return {
        ...state,
        videoTransform: { ...state.videoTransform, outline },
        isDirty: true,
      };
    }

    case "SET_LETTERBOX": {
      if (!action.letterbox) {
        // Strip the letterbox slot from the layer order when the operator
        // removes the letterbox (undefined → no slot).
        const layerOrder = state.layerOrder.filter(
          (l) => l.kind !== "letterbox",
        );
        return { ...state, letterbox: undefined, layerOrder, isDirty: true };
      }
      // Each bar capped at 50% (360 px on the 720-tall output canvas)
      // so the two bars together never fully cover the canvas.
      const topHeightPct = Math.max(0, Math.min(50, action.letterbox.topHeightPct));
      const bottomHeightPct = Math.max(
        0,
        Math.min(50, action.letterbox.bottomHeightPct),
      );
      // Q4 — outline (윤곽선) defaults: width seeded to 5 px the
      // moment the operator picks a colour. Caller may override but
      // doesn't need to.
      const borderColor = action.letterbox.borderColor ?? null;
      const borderWidthPx = Math.max(
        0,
        Math.min(50, action.letterbox.borderWidthPx),
      );
      // Insert the letterbox slot at index 1 (above video, below everything
      // else) only when the operator is adding it for the first time.
      // If already present (operator is adjusting height/color), leave
      // layerOrder unchanged so a manual reorder is not clobbered.
      const hasLetterboxSlot = state.layerOrder.some(
        (l) => l.kind === "letterbox",
      );
      const layerOrderForLetterbox: LayerOrderId[] = hasLetterboxSlot
        ? state.layerOrder
        : [
            state.layerOrder[0] ?? { kind: "video" },
            { kind: "letterbox" },
            ...state.layerOrder.slice(1),
          ];
      return {
        ...state,
        letterbox: {
          topHeightPct,
          bottomHeightPct,
          fillColor: action.letterbox.fillColor,
          borderColor,
          borderWidthPx,
        },
        layerOrder: layerOrderForLetterbox,
        isDirty: true,
      };
    }

    case "SET_PLAYHEAD":
      return { ...state, playheadMs: Math.max(0, action.ms) };

    case "PLAYBACK_EVENT": {
      const pb = reducePlayback(state.playback, action.event, state.playheadMs, state.totalDurationMs);
      if (pb === state.playback) return state;
      return { ...state, playback: pb };
    }

    case "SET_IN_POINT": {
      // L4 / T2 — clamp to [0, totalDurationMs] and to be < outPointMs
      // (if set) so the range can never collapse to negative length.
      // Passing null clears the mark.
      if (action.ms === null) return { ...state, inPointMs: null };
      const clamped = Math.max(0, Math.min(state.totalDurationMs, action.ms));
      const finalMs =
        state.outPointMs != null
          ? Math.min(clamped, Math.max(0, state.outPointMs - 1))
          : clamped;
      return { ...state, inPointMs: finalMs };
    }

    case "SET_OUT_POINT": {
      if (action.ms === null) return { ...state, outPointMs: null };
      const clamped = Math.max(0, Math.min(state.totalDurationMs, action.ms));
      const finalMs =
        state.inPointMs != null
          ? Math.max(clamped, state.inPointMs + 1)
          : clamped;
      return { ...state, outPointMs: finalMs };
    }

    case "SPLIT_SUBTITLE": {
      // L5 / T5 — slice the subtitle in two at atMs. No-op if atMs
      // doesn't strictly straddle the timing window (a split at the
      // exact edge would create a zero-duration block).
      const src = state.subtitles[action.index];
      if (!src) return state;
      if (action.atMs <= src.startMs || action.atMs >= src.endMs) return state;
      // Proportional text split: compute the time-fraction of the cut
      // within this subtitle's window and split the text at the nearest
      // eojeol (Korean word) boundary. Even with sentence-level seed STT
      // data (no word-level timestamps) the heuristic produces a
      // reasonable split at eojeol granularity.
      const subDuration = src.endMs - src.startMs;
      const fraction = subDuration > 0
        ? (action.atMs - src.startMs) / subDuration
        : 0.5;
      const [headText, tailText] = splitSubtitleText(src.text, fraction);
      const head = { ...src, text: headText, endMs: action.atMs };
      const tail = {
        ...src,
        id: generateSubtitleId(),
        text: tailText,
        startMs: action.atMs,
      };
      const subtitles = [...state.subtitles];
      subtitles.splice(action.index, 1, head, tail);
      // Also split any clip whose composition window straddles atMs.
      // No recomputeTimeline — splitClipsAtMs already sets correct
      // timelineStartMs for both head and tail.
      const clips = splitClipsAtMs(state.clips, action.atMs);
      // Selection stays on the head — the operator just split off the
      // tail, so the original selection's "anchor" is the head.
      return {
        ...state,
        subtitles,
        clips,
        totalDurationMs: getTotalDuration(clips),
        isDirty: true,
      };
    }

    case "SPLIT_OVERLAY": {
      const idx = state.overlays.findIndex((o) => o.id === action.id);
      if (idx < 0) return state;
      const src = state.overlays[idx];
      if (src.kind !== "text") return state; // only text overlays split
      if (action.atMs <= src.startMs || action.atMs >= src.endMs) return state;
      const head: typeof src = { ...src, endMs: action.atMs };
      const tail: typeof src = {
        ...src,
        id: generateOverlayId("text"),
        startMs: action.atMs,
      };
      const overlays = [...state.overlays];
      overlays.splice(idx, 1, head, tail);
      return { ...state, overlays, isDirty: true };
    }

    case "SPLIT_CLIP": {
      // Splitting a clip at timeline coord atMs means cutting it at
      // the SOURCE coord (clip.trimStartMs + (atMs - clip.timelineStartMs)).
      // Head keeps the original id; tail gets a fresh clip id and its
      // timeline position becomes atMs.
      const src = state.clips[action.index];
      if (!src) return state;
      const clipStart = src.timelineStartMs;
      const clipEnd = clipStart + (src.trimEndMs - src.trimStartMs);
      if (action.atMs <= clipStart || action.atMs >= clipEnd) return state;
      const sourceCut = src.trimStartMs + (action.atMs - clipStart);
      const head = { ...src, trimEndMs: sourceCut };
      const tail = {
        ...src,
        id: generateClipId(),
        trimStartMs: sourceCut,
        timelineStartMs: action.atMs,
      };
      const clips = [...state.clips];
      clips.splice(action.index, 1, head, tail);
      // No recomputeTimeline — gaps are allowed, and the head/tail
      // already have correct timelineStartMs values.
      // Also split any subtitle that straddles atMs within this clip's window.
      const subtitles = splitSubtitlesAtMs(state.subtitles, action.atMs, [clipStart, clipEnd]);
      return {
        ...state,
        clips,
        subtitles,
        totalDurationMs: getTotalDuration(clips),
        isDirty: true,
      };
    }

    case "SET_RAZOR_MODE":
      return { ...state, razorMode: action.active };

    case "SET_ZOOM":
      // Floor reduced from 25 → 0.1 so a multi-minute / multi-hour
      // video can fully zoom out (1300px viewport / 3600s = 0.36 px/s
      // for a 1 hr clip). UI-level clamp lives in TimelineZoomControl
      // where the dynamic min is computed from the actual duration.
      return { ...state, zoom: Math.max(0.1, Math.min(300, action.zoom)) };

    case "APPLY_COMPOSITION_TEMPLATE": {
      // Operator-confirmed semantics (2026-05-24):
      //   * subtitleStyle  → merge into every subtitle.style (text /
      //                      timing untouched). Skip when null.
      //   * overlays       → APPEND. Each payload overlay gets a fresh
      //                      id, startMs = current playhead, endMs =
      //                      playhead + durationMs.
      //   * letterbox      → SET (overwrite) when non-null; skip on null.
      //   * videoTransform → SET (overwrite).
      // The caller is expected to push a snapshot before dispatching
      // so Ctrl+Z reverts the whole apply in one stroke.
      const p = action.payload;

      // --- subtitle style merge -------------------------------------
      const subtitles =
        p.subtitleStyle == null
          ? state.subtitles
          : state.subtitles.map((s) => ({
              ...s,
              style: { ...s.style, ...p.subtitleStyle },
            }));

      // --- overlay append -------------------------------------------
      const playhead = state.playheadMs;
      // Highest existing layerIndex so appended overlays sit on top.
      const baseLayer = state.overlays.reduce(
        (m, o) => Math.max(m, o.layerIndex),
        -1,
      );
      const appendedOverlays: EditorOverlay[] = [];
      let nextLayer = baseLayer + 1;
      for (const item of p.overlays) {
        const id = generateOverlayId(item.kind === "text" ? "text" : "bg");
        const startMs = playhead;
        const endMs = playhead + Math.max(1, item.durationMs);
        // payload is the overlay body without identity/timing. Reattach
        // them along with the regenerated layerIndex so the new overlay
        // sits above the stack.
        const overlay = {
          ...(item.payload as object),
          kind: item.kind,
          id,
          startMs,
          endMs,
          layerIndex: nextLayer,
        } as EditorOverlay;
        appendedOverlays.push(overlay);
        nextLayer += 1;
      }
      const overlays = [...state.overlays, ...appendedOverlays];

      // --- letterbox SET --------------------------------------------
      const letterbox = p.letterbox
        ? {
            topHeightPct: p.letterbox.topHeightPct,
            bottomHeightPct: p.letterbox.bottomHeightPct,
            fillColor: p.letterbox.fillColor,
            borderColor: p.letterbox.borderColor,
            borderWidthPx: p.letterbox.borderWidthPx,
          }
        : state.letterbox;

      // --- videoTransform SET ---------------------------------------
      // outline rides along on the videoTransform payload so the
      // template carries the operator's border choice (Task 3 round-
      // trip). Missing on legacy payloads → null (no outline).
      const videoTransform = {
        x: p.videoTransform.x,
        y: p.videoTransform.y,
        scale: p.videoTransform.scale,
        // Legacy presets (pre-2026-05-24) didn't capture rotation /
        // shadow — treat their absence as defaults so the apply still
        // produces a valid state.
        rotationDeg: p.videoTransform.rotationDeg ?? 0,
        outline: p.videoTransform.outline ?? null,
        shadow: p.videoTransform.shadow ?? null,
      };

      // Rebuild layerOrder.
      //
      // When the preset carries a ``layerOrder`` snapshot (2026-05-25
      // round-trip), use it as the new stack base: overlay slot ids
      // get rewritten via an index-aligned old→new id map (preset
      // overlays[i] ↔ appendedOverlays[i]). Existing overlay slots
      // that the operator already had on the canvas are appended on
      // top so applying a preset is additive, not destructive.
      // Letterbox slot is normalised against the (possibly newly-set)
      // letterbox state.
      //
      // When the preset has no layerOrder (legacy presets pre-2026-05-25),
      // fall back to the previous behaviour: keep state.layerOrder and
      // simply append the new overlay slots on top.
      let layerOrder: LayerOrderId[];
      if (p.layerOrder && p.layerOrder.length > 0) {
        const idMap = new Map<string, string>();
        for (let i = 0; i < p.overlays.length; i += 1) {
          const presetId = p.overlays[i].id;
          if (presetId) idMap.set(presetId, appendedOverlays[i].id);
        }
        const mappedPresetOrder = p.layerOrder
          .map((l): LayerOrderId | null => {
            if (l.kind === "overlay") {
              const newId = idMap.get(l.id);
              return newId ? { kind: "overlay", id: newId } : null;
            }
            return { kind: l.kind };
          })
          .filter((l): l is LayerOrderId => l !== null);
        // Existing overlay slots (operator had overlays before applying)
        // — preserve order, drop any duplicates with appended ids.
        const appendedIds = new Set(appendedOverlays.map((o) => o.id));
        const existingOverlaySlots = state.layerOrder.filter(
          (l): l is LayerOrderId =>
            l.kind === "overlay" && !appendedIds.has(l.id),
        );
        layerOrder = [...mappedPresetOrder, ...existingOverlaySlots];
        // Letterbox slot consistency: if letterbox is now null, strip
        // any letterbox slot the preset may have carried. If letterbox
        // is set but the mapped order didn't include it, insert above
        // the video slot.
        if (letterbox == null) {
          layerOrder = layerOrder.filter((l) => l.kind !== "letterbox");
        } else if (!layerOrder.some((l) => l.kind === "letterbox")) {
          const videoIdx = layerOrder.findIndex((l) => l.kind === "video");
          const insertAt = videoIdx >= 0 ? videoIdx + 1 : 0;
          layerOrder.splice(insertAt, 0, { kind: "letterbox" });
        }
      } else {
        layerOrder = [
          ...state.layerOrder.filter(
            (l) => !(l.kind === "letterbox" && letterbox == null),
          ),
        ];
        if (letterbox && !layerOrder.some((l) => l.kind === "letterbox")) {
          const videoIdx = layerOrder.findIndex((l) => l.kind === "video");
          const insertAt = videoIdx >= 0 ? videoIdx + 1 : 0;
          layerOrder.splice(insertAt, 0, { kind: "letterbox" });
        }
        for (const o of appendedOverlays) {
          layerOrder.push({ kind: "overlay", id: o.id });
        }
      }

      // Final normalise — guarantees subtitles + text overlays sit
      // above any background overlay regardless of how the preset
      // captured them (operator policy 2026-05-25).
      const normalisedLayerOrder = normalizeLayerOrder(layerOrder, overlays);

      return {
        ...state,
        subtitles,
        overlays,
        letterbox,
        videoTransform,
        layerOrder: normalisedLayerOrder,
        isDirty: true,
      };
    }

    case "MARK_CLEAN":
      return { ...state, isDirty: false };

    case "PUSH_HISTORY": {
      // Cap the stack so a long editing session can't grow it
      // unboundedly. Older entries fall off the bottom — operators
      // get up to 50 reversible gestures, which mirrors the
      // industry-standard undo depth for design tools.
      const history = [...state.history, action.entry].slice(-HISTORY_LIMIT);
      // A fresh edit invalidates the redo chain (canonical undo/redo
      // semantics — operators expect Ctrl+Shift+Z to be a no-op after
      // they continue editing past an undo).
      return { ...state, history, redoHistory: [] };
    }

    case "UNDO": {
      const entry = state.history[state.history.length - 1];
      if (!entry) return state;
      const nextHistory = state.history.slice(0, -1);
      // Capture the current value of the entry's target so REDO can
      // re-apply it. The HistoryEntry shape already encodes the
      // entire property being restored, so the redo snapshot is just
      // the symmetric capture taken from current state.
      const captureRedo = captureRedoEntry(state, entry);
      const nextRedo = captureRedo
        ? [...state.redoHistory, captureRedo].slice(-HISTORY_LIMIT)
        : state.redoHistory;
      const restored = applyHistoryEntry(state, entry);
      return {
        ...restored,
        history: nextHistory,
        redoHistory: nextRedo,
        isDirty: true,
      };
    }

    case "REDO": {
      const entry = state.redoHistory[state.redoHistory.length - 1];
      if (!entry) return state;
      const nextRedo = state.redoHistory.slice(0, -1);
      // Symmetric to UNDO: take the current value of the entry's
      // target and push it back onto ``history`` so Ctrl+Z can roll
      // forward → back → forward.
      const captureUndo = captureRedoEntry(state, entry);
      const nextHistory = captureUndo
        ? [...state.history, captureUndo].slice(-HISTORY_LIMIT)
        : state.history;
      const restored = applyHistoryEntry(state, entry);
      return {
        ...restored,
        history: nextHistory,
        redoHistory: nextRedo,
        isDirty: true,
      };
    }

    default:
      return state;
  }
}

// Returns a HistoryEntry snapshot of the current value of the same
// target as ``entry``. Used by UNDO to populate ``redoHistory`` and by
// REDO to populate ``history`` — both directions need the symmetric
// "what is it now?" capture before mutating state.
function captureRedoEntry(
  state: EditorState,
  entry: HistoryEntry,
): HistoryEntry | null {
  switch (entry.kind) {
    case "subtitle_style": {
      const current = state.subtitles[entry.index]?.style;
      if (!current) return null;
      return { kind: "subtitle_style", index: entry.index, style: current };
    }
    case "subtitle_time": {
      const current = state.subtitles[entry.index];
      if (!current) return null;
      return {
        kind: "subtitle_time",
        index: entry.index,
        startMs: current.startMs,
        endMs: current.endMs,
      };
    }
    case "overlay_time": {
      const current = state.overlays.find((o) => o.id === entry.id);
      if (!current) return null;
      return {
        kind: "overlay_time",
        id: entry.id,
        startMs: current.startMs,
        endMs: current.endMs,
      };
    }
    case "overlay_transform": {
      const current = state.overlays.find((o) => o.id === entry.id);
      if (!current) return null;
      return { kind: "overlay_transform", id: entry.id, transform: current.transform };
    }
    case "overlay_font_size": {
      const current = state.overlays.find((o) => o.id === entry.id);
      if (!current || current.kind !== "text") return null;
      return { kind: "overlay_font_size", id: entry.id, fontSizePx: current.fontSizePx };
    }
    case "video_position": {
      return {
        kind: "video_position",
        x: state.videoTransform.x,
        y: state.videoTransform.y,
      };
    }
    case "video_scale": {
      return { kind: "video_scale", scale: state.videoTransform.scale };
    }
    case "video_rotation": {
      return {
        kind: "video_rotation",
        rotationDeg: state.videoTransform.rotationDeg,
      };
    }
    case "video_outline": {
      return {
        kind: "video_outline",
        outline: state.videoTransform.outline ?? null,
      };
    }
    case "video_shadow": {
      return {
        kind: "video_shadow",
        shadow: state.videoTransform.shadow ?? null,
      };
    }
    case "letterbox": {
      return { kind: "letterbox", letterbox: state.letterbox };
    }
    case "snapshot": {
      // Capture the post-action state so REDO can re-apply the change
      // after an UNDO. We deliberately blank history/redoHistory in
      // the captured copy — those are managed by UNDO / REDO outside
      // applyHistoryEntry and must not get rolled into the snapshot,
      // otherwise the redo stack would be carried inside its own
      // capture.
      return {
        kind: "snapshot",
        state: { ...state, history: [], redoHistory: [] },
      };
    }
  }
}

// Applies a HistoryEntry to state — used by both UNDO (restoring the
// pre-gesture state) and REDO (re-applying the previously-undone
// state). Mutates only the property the entry describes, leaving all
// other state slots untouched.
function applyHistoryEntry(state: EditorState, entry: HistoryEntry): EditorState {
  switch (entry.kind) {
    case "subtitle_style": {
      const subtitles = state.subtitles.map((s, i) =>
        i === entry.index ? { ...s, style: entry.style } : s,
      );
      return { ...state, subtitles };
    }
    case "subtitle_time": {
      const subtitles = state.subtitles.map((s, i) =>
        i === entry.index
          ? { ...s, startMs: entry.startMs, endMs: entry.endMs }
          : s,
      );
      return { ...state, subtitles };
    }
    case "overlay_time": {
      const overlays = state.overlays.map((o) =>
        o.id === entry.id
          ? ({ ...o, startMs: entry.startMs, endMs: entry.endMs } as typeof o)
          : o,
      );
      return { ...state, overlays };
    }
    case "overlay_transform": {
      const overlays = state.overlays.map((o) =>
        o.id === entry.id ? ({ ...o, transform: entry.transform } as typeof o) : o,
      );
      return { ...state, overlays };
    }
    case "overlay_font_size": {
      const overlays = state.overlays.map((o) =>
        o.id === entry.id && o.kind === "text"
          ? ({ ...o, fontSizePx: entry.fontSizePx } as typeof o)
          : o,
      );
      return { ...state, overlays };
    }
    case "video_position": {
      return {
        ...state,
        videoTransform: { ...state.videoTransform, x: entry.x, y: entry.y },
      };
    }
    case "video_scale": {
      return {
        ...state,
        videoTransform: { ...state.videoTransform, scale: entry.scale },
      };
    }
    case "video_rotation": {
      return {
        ...state,
        videoTransform: {
          ...state.videoTransform,
          rotationDeg: entry.rotationDeg,
        },
      };
    }
    case "video_outline": {
      return {
        ...state,
        videoTransform: { ...state.videoTransform, outline: entry.outline },
      };
    }
    case "video_shadow": {
      return {
        ...state,
        videoTransform: { ...state.videoTransform, shadow: entry.shadow },
      };
    }
    case "letterbox": {
      return { ...state, letterbox: entry.letterbox };
    }
    case "snapshot": {
      // Restore every slot from the snapshot — except history /
      // redoHistory, which UNDO / REDO manage on the calling side and
      // must not be clobbered. The snapshot's own history fields are
      // intentionally blank (see captureRedoEntry above).
      return {
        ...entry.state,
        history: state.history,
        redoHistory: state.redoHistory,
      };
    }
  }
}

let _clipCounter = 0;
export function generateClipId(): string {
  return `clip_${Date.now()}_${++_clipCounter}`;
}

let _subtitleCounter = 0;
export function generateSubtitleId(): string {
  return `sub_${Date.now()}_${++_subtitleCounter}`;
}

export function createClipFromScene(
  scene: { scene_id: string; start_ms: number; end_ms: number; scene_caption?: string; ai_tags?: string[] },
  videoId: string,
  sourceType: string,
): EditorClip {
  const label = scene.scene_caption?.slice(0, 30) || scene.ai_tags?.[0] || undefined;
  return {
    id: generateClipId(),
    sceneId: scene.scene_id,
    videoId,
    sourceType,
    originalStartMs: scene.start_ms,
    originalEndMs: scene.end_ms,
    trimStartMs: scene.start_ms,
    trimEndMs: scene.end_ms,
    timelineStartMs: 0,
    volume: 1.0,
    label,
  };
}

/**
 * Parse a timestamp string like "1:23" or "0:05" into milliseconds.
 */
function parseTimestampMs(ts: string): number | null {
  const parts = ts.split(":").map(Number);
  if (parts.some(isNaN)) return null;
  if (parts.length === 3) return (parts[0] * 3600 + parts[1] * 60 + parts[2]) * 1000;
  if (parts.length === 2) return (parts[0] * 60 + parts[1]) * 1000;
  return null;
}

// Sentence-ending patterns (Korean + Latin) — primary split.
const SENTENCE_SPLIT_RE = /(?<=[.!?。])\s+|(?<=[요다죠음네까게세지]\.?\s)/g;

// Korean clause-boundary patterns — secondary split for finer chunks.
// Conjunctive endings ("는데", "면서요", "이기 때문에", etc.) and
// connective particles mark natural pause points where Korean speakers
// breathe. Matching these gives subtitles that flow with speech rather
// than dumping a whole turn into one block.
//
// Each pattern uses a positive lookbehind so the boundary stays attached
// to the LEFT chunk (e.g., "...이벤트이기 | 때문에" → "이벤트이기"
// stays as one chunk's tail, "때문에" starts the next).
const CLAUSE_SPLIT_RE = /(?<=,)\s+|(?<=[는면서고지만니까데서야면])\s+(?=[가-힣])/g;

// 25 chars is roughly 5-7 Korean eojeol — short enough to read in 1-2s
// at typical livecommerce pacing, long enough to avoid choppy 2-word
// fragments. Calibrated against the operator-target screenshot where
// rows ranged 3-16 chars.
const MAX_SUBTITLE_CHARS = 25;
const SUBTITLE_FONT_SIZE = 24;

/**
 * Split text into subtitle-friendly chunks that flow naturally with
 * speech. Two-pass split: sentence boundaries first, then Korean
 * clause boundaries within each sentence; falls back to greedy
 * eojeol-by-eojeol packing for runaway sentences with no commas or
 * conjunctive endings.
 *
 * Goal: each chunk reads in ~1-2s at livecommerce pace, matching the
 * operator-target inline-editor UX (Clip 1-N "자동 자막" panel).
 */
function chunkSubtitleText(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.length <= MAX_SUBTITLE_CHARS) return [trimmed];

  // Pass 1: sentence-level split.
  const sentences = trimmed.split(SENTENCE_SPLIT_RE).filter((s) => s.trim());
  const chunks: string[] = [];

  for (const sentence of sentences) {
    if (sentence.length <= MAX_SUBTITLE_CHARS) {
      chunks.push(sentence.trim());
      continue;
    }
    // Pass 2: clause-level split inside an oversize sentence.
    const clauses = sentence
      .split(CLAUSE_SPLIT_RE)
      .map((c) => c.trim())
      .filter(Boolean);

    let current = "";
    for (const clause of clauses) {
      if (clause.length > MAX_SUBTITLE_CHARS) {
        // Pass 3: eojeol greedy pack — fall through when a single
        // clause is still too long (no clause boundary inside).
        if (current) {
          chunks.push(current);
          current = "";
        }
        const eojeols = clause.split(/\s+/);
        let buf = "";
        for (const e of eojeols) {
          const next = buf ? `${buf} ${e}` : e;
          if (next.length > MAX_SUBTITLE_CHARS) {
            if (buf) chunks.push(buf);
            buf = e;
          } else {
            buf = next;
          }
        }
        if (buf) {
          // Hold the tail in `current` so the next clause can
          // potentially co-pack with it (don't push prematurely).
          current = buf;
        }
        continue;
      }
      const candidate = current ? `${current} ${clause}` : clause;
      if (candidate.length <= MAX_SUBTITLE_CHARS) {
        current = candidate;
      } else {
        if (current) chunks.push(current);
        current = clause;
      }
    }
    if (current) chunks.push(current);
  }

  return chunks.length > 0 ? chunks : [trimmed.slice(0, MAX_SUBTITLE_CHARS)];
}

/**
 * Generate subtitle blocks from a scene's speaker transcript.
 * Long turns are chunked into ~60-char segments for readable display.
 */
export function generateSubtitlesFromTranscript(
  speakerTranscript: string | undefined | null,
  clip: EditorClip,
): EditorSubtitle[] {
  let turns = parseSpeakerTranscript(speakerTranscript);
  // Fallback: scenes without the ``SPEAKER_XX [m:ss]: text`` envelope
  // (e.g., raw transcripts piped in from older indexing runs) parse to
  // zero turns even when they carry usable text. When that happens we
  // synthesize a single untimed turn from the original string so the
  // even-distribution branch below still produces subtitles. Without
  // this, /videos → editor entries with non-speaker-tagged transcripts
  // landed in the editor with an empty subtitle list.
  if (turns.length === 0) {
    const raw = (speakerTranscript ?? "").trim();
    if (!raw) return [];
    turns = [
      {
        rawId: "UNTAGGED",
        label: "A",
        color: { bg: "", text: "", border: "" },
        text: raw,
        timestamp: null,
      },
    ];
  }

  const clipDuration = clip.trimEndMs - clip.trimStartMs;
  const style = { ...DEFAULT_SUBTITLE_STYLE, fontSizePx: SUBTITLE_FONT_SIZE };

  // Flatten all turns into text chunks for even timing
  const allChunks: string[] = [];
  for (const turn of turns) {
    allChunks.push(...chunkSubtitleText(turn.text));
  }

  if (allChunks.length === 0) return [];

  // Check if turns have usable timestamps
  const turnsWithTs = turns
    .map((turn) => ({ turn, ms: turn.timestamp ? parseTimestampMs(turn.timestamp) : null }))
    .filter((t) => t.ms != null) as Array<{ turn: typeof turns[0]; ms: number }>;

  const subtitles: EditorSubtitle[] = [];

  // Transcripts can store timestamps two ways: absolute video time
  // (offset from video start, so offsetMs ≥ clip.trimStartMs) or
  // scene-relative (offset from scene start, so offsetMs ≥ 0 and
  // < clipDuration). Sample EVERY turn against both interpretations and
  // commit to whichever fits more turns inside the scene window — a
  // single-turn sample (the previous heuristic) flipped to interpretRel
  // on stray near-zero timestamps and crammed unrelated text into the
  // scene. Ties break toward interpretAbs (the more conservative read).
  // The timed loop below filters per-turn out-of-range entries so a
  // mismatched transcript naturally produces few/no subtitles via the
  // same gate, rather than via a brittle confidence threshold that
  // dropped legitimate single-turn scenes (regression surfaced 2026-05-18).
  const interpretAbs = (offsetMs: number) => offsetMs - clip.trimStartMs;
  const interpretRel = (offsetMs: number) => offsetMs;
  let interpretMs: (offsetMs: number) => number = interpretAbs;
  if (turnsWithTs.length > 0) {
    let absHits = 0;
    let relHits = 0;
    for (const { ms } of turnsWithTs) {
      const a = interpretAbs(ms);
      if (a >= 0 && a < clipDuration) absHits++;
      const r = interpretRel(ms);
      if (r >= 0 && r < clipDuration) relHits++;
    }
    interpretMs = absHits >= relHits ? interpretAbs : interpretRel;
  }

  if (turnsWithTs.length > 0) {
    // Timestamp-based: chunk each turn, distribute chunks within the
    // turn's time slot. 2026-05-18 — three accuracy improvements over
    // the previous even-split:
    //
    //   1. ``slotDuration`` no longer caps at 9s (was
    //      ``DEFAULT_SUBTITLE_DURATION_MS * 3``). A long monologue used
    //      to leave the back of the turn silent because chunks ran out
    //      after 9s; now the chunks fill all the way to the next
    //      turn's timestamp (or clip end).
    //   2. Per-chunk duration is weighted by character count rather
    //      than split evenly. Korean speech runs ≈ 7 chars/sec, so
    //      sentence-length variance maps to time-length variance —
    //      short clauses get short subtitles and long sentences get
    //      proportionally longer ones. Lower bound 800ms keeps very
    //      short chunks readable; upper bound 4000ms prevents one
    //      sentence dominating a long turn.
    //   3. Per-chunk ceiling (PER_CHUNK_MAX_MS) caps the longest
    //      individual subtitle at 4s so a 30s-turn monologue still
    //      reads in digestible bites, even after the 9s cap is gone.
    const PER_CHUNK_MIN_MS = 800;
    const PER_CHUNK_MAX_MS = 4000;
    for (let i = 0; i < turnsWithTs.length; i++) {
      const { turn, ms: offsetMs } = turnsWithTs[i];
      const relativeMs = interpretMs(offsetMs);
      if (relativeMs < 0 || relativeMs >= clipDuration) continue;

      const nextRelative = i + 1 < turnsWithTs.length
        ? interpretMs(turnsWithTs[i + 1].ms)
        : clipDuration;
      const slotDuration = Math.max(0, nextRelative - relativeMs);

      const chunks = chunkSubtitleText(turn.text);
      if (chunks.length === 0) continue;
      const totalChars = chunks.reduce((sum, c) => sum + c.length, 0) || 1;

      let cursor = relativeMs;
      for (let j = 0; j < chunks.length; j++) {
        if (cursor >= clipDuration) break;
        // Weighted slice of the turn's time slot.
        const share = chunks[j].length / totalChars;
        const ideal = Math.floor(slotDuration * share);
        const duration = Math.min(
          PER_CHUNK_MAX_MS,
          Math.max(PER_CHUNK_MIN_MS, ideal),
        );
        const startMs = cursor;
        const endMs = Math.min(startMs + duration, clipDuration);

        subtitles.push({
          id: generateSubtitleId(),
          text: chunks[j],
          startMs: clip.timelineStartMs + startMs,
          endMs: clip.timelineStartMs + endMs,
          style: { ...style },
        });
        cursor = endMs;
      }
    }
  }

  // Fall through to even-distribution whenever the timestamp branch
  // produced nothing — happens both when the transcript has no
  // timestamps at all and when every timestamp fell outside the scene
  // window. The earlier turnsWithTs-only gate stopped subtitles from
  // showing for scenes whose stamps were slightly out of range, which
  // surfaced as "subtitles aren't loading anymore" on 2026-05-18. The
  // cross-runtime symptom this gate guarded against is rarer than
  // legitimate off-by-a-bit stamps, so we accept the trade and let
  // operators delete unwanted lines manually.
  if (subtitles.length === 0) {
    // No timestamps: distribute all chunks evenly across clip
    const chunkDuration = Math.max(800, Math.floor(clipDuration / allChunks.length));
    if (chunkDuration < 500) return [];

    for (let i = 0; i < allChunks.length; i++) {
      const startMs = clip.timelineStartMs + i * chunkDuration;
      if (startMs >= clip.timelineStartMs + clipDuration) break;
      const endMs = Math.min(startMs + chunkDuration, clip.timelineStartMs + clipDuration);

      subtitles.push({
        id: generateSubtitleId(),
        text: allChunks[i],
        startMs,
        endMs,
        style: { ...style },
      });
    }
  }

  return subtitles;
}

export function useEditorState() {
  const [state, dispatch] = useReducer(editorReducer, INITIAL_STATE);

  // PR 5 follow-up — hybrid undo entry point for complex actions.
  // Pushes the CURRENT state as a snapshot HistoryEntry so the next
  // mutation can be rolled back as one stroke. Factory functions
  // below call this before dispatching add/remove/trim/reorder-style
  // actions; simple transforms keep their inverse-action history.
  //
  // Reads state through a ref so the callback identity stays stable
  // across renders. Without the ref, every state change would
  // re-create pushSnapshot, which would in turn invalidate every
  // factory's useCallback dep list — a single missed dep would land
  // a stale snapshot in history (the bug pattern that caused the
  // initial trimClip / reorderOverlay test failures).
  const stateRef = useRef(state);
  stateRef.current = state;
  const pushSnapshot = useCallback(() => {
    dispatch({
      type: "PUSH_HISTORY",
      entry: { kind: "snapshot", state: stateRef.current },
    });
  }, []);

  const initFromScenes = useCallback(
    (videoId: string, sourceType: string, clips: EditorClip[]) => {
      // INIT actions reset the editor — there's no meaningful "before"
      // to snapshot, and snapshotting an empty state would let UNDO
      // strand the operator with a blank canvas.
      dispatch({ type: "INIT_FROM_SCENES", videoId, sourceType, clips });
    },
    [],
  );

  const initFromComposition = useCallback((partial: Partial<EditorState>) => {
    // Same rationale as initFromScenes — bootstrap path, never an
    // operator gesture.
    dispatch({ type: "INIT_FROM_COMPOSITION", state: partial });
  }, []);

  const addClip = useCallback((clip: EditorClip) => {
    pushSnapshot();
    dispatch({ type: "ADD_CLIP", clip });
  }, [pushSnapshot]);

  const removeClip = useCallback((index: number) => {
    pushSnapshot();
    dispatch({ type: "REMOVE_CLIP", index });
  }, [pushSnapshot]);

  const reorderClips = useCallback((fromIndex: number, toIndex: number) => {
    pushSnapshot();
    dispatch({ type: "REORDER_CLIPS", fromIndex, toIndex });
  }, [pushSnapshot]);

  const trimClip = useCallback(
    (index: number, trimStartMs?: number, trimEndMs?: number) => {
      pushSnapshot();
      dispatch({ type: "TRIM_CLIP", index, trimStartMs, trimEndMs });
    },
    [pushSnapshot],
  );

  const moveClip = useCallback(
    (index: number, timelineStartMs: number) => {
      dispatch({ type: "MOVE_CLIP", index, timelineStartMs });
    },
    [],
  );

  const setClipVolume = useCallback((index: number, volume: number) => {
    dispatch({ type: "SET_CLIP_VOLUME", index, volume });
  }, []);

  const selectClip = useCallback((index: number | null) => {
    dispatch({ type: "SELECT_CLIP", index });
  }, []);

  const addSubtitle = useCallback((subtitle: EditorSubtitle) => {
    dispatch({ type: "ADD_SUBTITLE", subtitle });
  }, []);

  const addOverlayAtPlayhead = useCallback(() => {
    const totalMs = state.totalDurationMs;
    const startMs = Math.max(0, Math.min(state.playheadMs, Math.max(0, totalMs - 500)));
    const endMs = totalMs > 0
      ? Math.min(startMs + DEFAULT_SUBTITLE_DURATION_MS, totalMs)
      : startMs + DEFAULT_SUBTITLE_DURATION_MS;
    const subtitle: EditorSubtitle = {
      id: generateSubtitleId(),
      text: "",
      startMs,
      endMs,
      style: { ...DEFAULT_SUBTITLE_STYLE },
    };
    const newIndex = state.subtitles.length;
    pushSnapshot();
    dispatch({ type: "ADD_SUBTITLE", subtitle });
    dispatch({ type: "SELECT_SUBTITLE", index: newIndex });
  }, [state.playheadMs, state.totalDurationMs, state.subtitles.length, pushSnapshot]);

  const updateSubtitle = useCallback(
    (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => {
      // Snapshot for text edits (D5 hybrid — complex action). Style /
      // timing updates already get snapshotted by their drag-pointer
      // handlers via subtitle_style / subtitle_time inverse entries,
      // so we only snapshot when the call is changing text content.
      // Burst-typing still pushes one snapshot per keystroke, which is
      // chatty but bounded by HISTORY_LIMIT — debouncing this is a
      // future refinement.
      if ("text" in updates) pushSnapshot();
      dispatch({ type: "UPDATE_SUBTITLE", index, updates });
    },
    [pushSnapshot],
  );

  const removeSubtitle = useCallback((index: number) => {
    pushSnapshot();
    dispatch({ type: "REMOVE_SUBTITLE", index });
  }, [pushSnapshot]);

  const selectSubtitle = useCallback((index: number | null) => {
    dispatch({ type: "SELECT_SUBTITLE", index });
  }, []);

  const updateAllSubtitleStyles = useCallback(
    (updates: Partial<SubtitleStyle>) => {
      pushSnapshot();
      dispatch({ type: "UPDATE_ALL_SUBTITLE_STYLES", updates });
    },
    [pushSnapshot],
  );

  // Composition template apply — wraps a single snapshot around the
  // reducer dispatch so Ctrl+Z reverts the entire apply (subtitle
  // style merge + overlay append + letterbox set + video transform
  // set) in one stroke per operator request 2026-05-24.
  const applyCompositionTemplate = useCallback(
    (payload: import("../lib/overlay-types").CompositionPresetPayload) => {
      pushSnapshot();
      dispatch({ type: "APPLY_COMPOSITION_TEMPLATE", payload });
    },
    [pushSnapshot],
  );

  // ----- V2 overlay actions ------------------------------------------------

  const _clampOverlayWindow = (playheadMs: number, totalMs: number) => {
    const startMs = Math.max(0, Math.min(playheadMs, Math.max(0, totalMs - 500)));
    const endMs = totalMs > 0
      ? Math.min(startMs + DEFAULT_OVERLAY_DURATION_MS, totalMs)
      : startMs + DEFAULT_OVERLAY_DURATION_MS;
    return { startMs, endMs };
  };

  // Operator's '텍스트 추가' button — defaults the new overlay to
  // span the ENTIRE clip duration (per the 2026-05-22 Figma timeline
  // brief: the new text-overlay track is full-clip by default; the
  // operator can shorten or reposition the block afterwards). The
  // legacy 3-second playhead-relative window felt arbitrary and
  // didn't match the visual model where the top track is a single
  // wide bar.
  const addTextOverlayAtPlayhead = useCallback(() => {
    const totalMs =
      state.totalDurationMs > 0
        ? state.totalDurationMs
        : DEFAULT_OVERLAY_DURATION_MS;
    pushSnapshot();
    dispatch({
      type: "ADD_OVERLAY",
      overlay: createDefaultTextOverlay({ startMs: 0, endMs: totalMs }),
    });
  }, [state.totalDurationMs, pushSnapshot]);

  // Auto-subtitle path needs explicit timing + pre-filled text. The
  // playhead-based helper above can't fill text, and the V2 timeline only
  // renders text overlays — V1 subtitles in state.subtitles never make it
  // onto the timeline when isShortsEditorV2Enabled() is true. This helper
  // lets the page-level effect insert a fully-formed overlay (timing+text)
  // so generated subtitles light up the V2 timeline immediately.
  const addTextOverlay = useCallback(
    (params: { text: string; startMs: number; endMs: number }) => {
      const overlay = createDefaultTextOverlay({
        startMs: params.startMs,
        endMs: params.endMs,
      });
      pushSnapshot();
      dispatch({
        type: "ADD_OVERLAY",
        overlay: { ...overlay, text: params.text },
      });
    },
    [pushSnapshot],
  );

  // Hydration helper — drop a fully-formed overlay (already carrying
  // its own timing + style) straight into state. Used by the composition
  // loader to push saved/refined subtitles into the V2 overlays slice
  // without round-tripping through the playhead-relative add helpers.
  // The reducer's ADD_OVERLAY handler still rewrites layerIndex so
  // callers don't need to manage stacking.
  const addOverlayDirect = useCallback((overlay: EditorOverlay) => {
    dispatch({ type: "ADD_OVERLAY", overlay });
  }, []);

  // Starter caption templates (lib/starter-templates.ts) ship with a
  // full style payload (text + font + position + stroke/shadow). This
  // helper splices in the playhead-derived timing so the operator can
  // drop a template at the current cursor with one click.
  // Starter templates follow the same '텍스트 추가' = full-clip
  // default as addTextOverlayAtPlayhead. Operator can then shorten /
  // reposition like any other overlay.
  const addStarterTextOverlay = useCallback(
    (style: StarterTemplateStyle) => {
      const totalMs =
        state.totalDurationMs > 0
          ? state.totalDurationMs
          : DEFAULT_OVERLAY_DURATION_MS;
      pushSnapshot();
      dispatch({
        type: "ADD_OVERLAY",
        overlay: {
          kind: "text",
          id: generateOverlayId("text"),
          startMs: 0,
          endMs: totalMs,
          layerIndex: 0,
          ...style,
        },
      });
    },
    [state.totalDurationMs, pushSnapshot],
  );

  // Solid color backgrounds span the whole timeline AND fill the full
  // canvas — used to cover the black letterbox area when a 16:9 clip
  // sits inside the 9:16 frame (2026-05-18 review).
  const addBackgroundOverlayAtPlayhead = useCallback(
    (fillColor?: string) => {
      const totalMs = state.totalDurationMs > 0
        ? state.totalDurationMs
        : DEFAULT_OVERLAY_DURATION_MS;
      const overlay = createDefaultBackgroundOverlay({
        startMs: 0,
        endMs: totalMs,
        fillColor,
      });
      overlay.transform = {
        ...overlay.transform,
        widthPx: DEFAULT_OUTPUT.width,
        heightPx: DEFAULT_OUTPUT.height,
      };
      pushSnapshot();
      dispatch({ type: "ADD_OVERLAY", overlay });
    },
    [state.totalDurationMs, pushSnapshot],
  );

  // Image insert is intentionally NOT canvas-sized — the operator
  // wants the picture to retain its natural aspect, centered on the
  // preview, with the renderer's "contain" sizing fitting it into the
  // canvas. We span the whole timeline so the image persists for the
  // full composition, but we leave width/height at the factory default
  // so the picture isn't stretched to the 9:16 frame.
  // 2026-05-19 — operator feedback: a 480×480 square was awkward to
  // resize when the user dropped in a landscape product still. The
  // helper now async-loads the source to read naturalWidth /
  // naturalHeight, computes a width = 2/3 of the canvas (~270px at
  // the 405px output), and derives height from the natural aspect.
  // The picture lands at a comfortable two-thirds-of-frame size with
  // its original proportions intact. Falls back to the factory
  // default (480×480 from createDefaultBackgroundOverlay) if the
  // image fails to load — e.g. a malformed data URL.
  const addImageBackgroundOverlayAtPlayhead = useCallback(
    (imageUrl: string) => {
      const totalMs =
        state.totalDurationMs > 0
          ? state.totalDurationMs
          : DEFAULT_OVERLAY_DURATION_MS;
      const dispatchOverlay = (sizeOverride: {
        widthPx: number;
        heightPx: number;
      } | null) => {
        const overlay = createDefaultBackgroundOverlay({
          startMs: 0,
          endMs: totalMs,
          imageUrl,
        });
        if (sizeOverride) {
          overlay.transform = {
            ...overlay.transform,
            widthPx: sizeOverride.widthPx,
            heightPx: sizeOverride.heightPx,
          };
        }
        pushSnapshot();
        dispatch({ type: "ADD_OVERLAY", overlay });
      };
      const img = new Image();
      img.onload = () => {
        if (img.naturalWidth <= 0 || img.naturalHeight <= 0) {
          dispatchOverlay(null);
          return;
        }
        const widthPx = Math.round((DEFAULT_OUTPUT.width * 2) / 3);
        const heightPx = Math.round(
          (widthPx * img.naturalHeight) / img.naturalWidth,
        );
        dispatchOverlay({ widthPx, heightPx });
      };
      img.onerror = () => dispatchOverlay(null);
      img.src = imageUrl;
    },
    [state.totalDurationMs, pushSnapshot],
  );

  const updateOverlay = useCallback(
    (id: string, updates: Partial<EditorOverlay>) => {
      // Skip snapshot when the only fields being updated are the ones
      // the drag pipeline writes (transform / fontSizePx). Those have
      // dedicated inverse entries pushed on pointerdown so a per-move
      // snapshot would duplicate history and explode the stack. Other
      // updates (fillColor, imageUrl, text, fontFamily, etc) flow
      // from panel controls that DON'T push their own history, so we
      // snapshot before applying.
      const dragOnlyKeys = new Set(["transform", "fontSizePx"]);
      const hasContentChange = Object.keys(updates).some(
        (k) => !dragOnlyKeys.has(k),
      );
      if (hasContentChange) pushSnapshot();
      dispatch({ type: "UPDATE_OVERLAY", id, updates });
    },
    [pushSnapshot],
  );

  const removeOverlay = useCallback((id: string) => {
    pushSnapshot();
    dispatch({ type: "REMOVE_OVERLAY", id });
  }, [pushSnapshot]);

  const selectOverlay = useCallback((id: string | null) => {
    dispatch({ type: "SELECT_OVERLAY", id });
  }, []);

  // 2026-05-24 — selection slots for the host video element and the
  // letterbox. Clicking the corresponding region in the preview canvas
  // dispatches these; mutual-exclusion semantics live in the reducer.
  const selectVideo = useCallback((active: boolean) => {
    dispatch({ type: "SELECT_VIDEO", active });
  }, []);

  const selectLetterbox = useCallback((active: boolean) => {
    dispatch({ type: "SELECT_LETTERBOX", active });
  }, []);

  // Clears every selection slot in one dispatch — useful for the preview
  // canvas background click. Cheaper than dispatching five separate
  // clears (each of which would mutate state and rerender).
  const clearAllSelections = useCallback(() => {
    dispatch({ type: "SELECT_CLIP", index: null });
    dispatch({ type: "SELECT_SUBTITLE", index: null });
    dispatch({ type: "SELECT_OVERLAY", id: null });
    dispatch({ type: "SELECT_VIDEO", active: false });
    dispatch({ type: "SELECT_LETTERBOX", active: false });
  }, []);

  const reorderOverlay = useCallback(
    (id: string, direction: "front" | "back" | "forward" | "backward") => {
      pushSnapshot();
      dispatch({ type: "REORDER_OVERLAY", id, direction });
    },
    [pushSnapshot],
  );

  const setPlayhead = useCallback((ms: number) => {
    dispatch({ type: "SET_PLAYHEAD", ms });
  }, []);

  const dispatchPlaybackEvent = useCallback((event: PlaybackEvent) => {
    dispatch({ type: "PLAYBACK_EVENT", event });
  }, []);

  const setPlaying = useCallback((playing: boolean) => {
    dispatchPlaybackEvent(playing ? { kind: "TOGGLE" } : { kind: "HARD_PAUSE" });
  }, [dispatchPlaybackEvent]);

  const setZoom = useCallback((zoom: number) => {
    dispatch({ type: "SET_ZOOM", zoom });
  }, []);

  // L4 / T2 — export range marks. Passing null clears.
  const setInPoint = useCallback((ms: number | null) => {
    dispatch({ type: "SET_IN_POINT", ms });
  }, []);
  const setOutPoint = useCallback((ms: number | null) => {
    dispatch({ type: "SET_OUT_POINT", ms });
  }, []);

  // L5 / T5 — split / razor. Pushes a snapshot before dispatching so
  // Ctrl+Z rolls back the entire split (both head and tail) in one
  // stroke. The reducer dispatches a no-op when atMs doesn't straddle
  // the target, so the snapshot is wasted in that case — acceptable
  // trade-off versus duplicating the "straddle" guard here.
  const splitSubtitle = useCallback(
    (index: number, atMs: number) => {
      pushSnapshot();
      dispatch({ type: "SPLIT_SUBTITLE", index, atMs });
    },
    [pushSnapshot],
  );
  const splitOverlay = useCallback(
    (id: string, atMs: number) => {
      pushSnapshot();
      dispatch({ type: "SPLIT_OVERLAY", id, atMs });
    },
    [pushSnapshot],
  );
  const splitClip = useCallback(
    (index: number, atMs: number) => {
      pushSnapshot();
      dispatch({ type: "SPLIT_CLIP", index, atMs });
    },
    [pushSnapshot],
  );
  // Razor-key dispatcher (S). Priority clip > overlay > subtitle —
  // mirrors the Delete-key precedence so the operator's mental model
  // stays consistent. Reads ``stateRef`` so we always split against
  // the latest playhead/selection, no stale-closure risk.
  const setRazorMode = useCallback((active: boolean) => {
    dispatch({ type: "SET_RAZOR_MODE", active });
  }, []);

  const splitAtPlayhead = useCallback(() => {
    const s = stateRef.current;
    if (s.selectedClipIndex != null) {
      splitClip(s.selectedClipIndex, s.playheadMs);
    } else if (s.selectedOverlayId != null) {
      splitOverlay(s.selectedOverlayId, s.playheadMs);
    } else if (s.selectedSubtitleIndex != null) {
      splitSubtitle(s.selectedSubtitleIndex, s.playheadMs);
    }
  }, [splitClip, splitOverlay, splitSubtitle]);

  const markClean = useCallback(() => {
    dispatch({ type: "MARK_CLEAN" });
  }, []);

  // Push a "pre-gesture" snapshot onto the undo stack. Callers invoke
  // this from pointerdown handlers (move / resize / rotate / time-drag)
  // so that the very first pointermove already has a committed entry
  // to roll back to. Repeated pointerdowns produce one entry each.
  const updateVideoPosition = useCallback((x: number, y: number) => {
    dispatch({ type: "UPDATE_VIDEO_POSITION", x, y });
  }, []);

  const updateVideoScale = useCallback((scale: number) => {
    dispatch({ type: "UPDATE_VIDEO_SCALE", scale });
  }, []);

  const updateVideoRotation = useCallback((rotationDeg: number) => {
    dispatch({ type: "UPDATE_VIDEO_ROTATION", rotationDeg });
  }, []);

  // Operator-facing outline (윤곽선) toggle. Pushes the previous
  // outline onto history so Ctrl+Z restores it in one stroke — same
  // pattern as setLetterbox in the page-level wrapper.
  const setVideoOutline = useCallback(
    (outline: { color: string; widthPx: number } | null) => {
      dispatch({
        type: "PUSH_HISTORY",
        entry: {
          kind: "video_outline",
          outline: stateRef.current.videoTransform.outline ?? null,
        },
      });
      dispatch({ type: "SET_VIDEO_OUTLINE", outline });
    },
    [],
  );

  // Operator-facing drop shadow toggle. Same history pattern as
  // setVideoOutline above — snapshot the pre-change shadow so Ctrl+Z
  // restores it cleanly.
  const setVideoShadow = useCallback(
    (
      shadow: {
        color: string;
        offsetX: number;
        offsetY: number;
        blurPx: number;
        spreadPx: number;
      } | null,
    ) => {
      dispatch({
        type: "PUSH_HISTORY",
        entry: {
          kind: "video_shadow",
          shadow: stateRef.current.videoTransform.shadow ?? null,
        },
      });
      dispatch({ type: "SET_VIDEO_SHADOW", shadow });
    },
    [],
  );

  const reorderLayer = useCallback(
    (layer: LayerOrderId, direction: "front" | "back" | "forward" | "backward") => {
      pushSnapshot();
      dispatch({ type: "REORDER_LAYER", layer, direction });
    },
    [pushSnapshot],
  );

  const setLetterbox = useCallback(
    (letterbox: EditorState["letterbox"]) => {
      dispatch({ type: "SET_LETTERBOX", letterbox });
    },
    [],
  );

  const pushHistory = useCallback((entry: HistoryEntry) => {
    dispatch({ type: "PUSH_HISTORY", entry });
  }, []);

  // Pop the most recent history entry and apply its reverse. No-op
  // when the stack is empty — Ctrl+Z at session start does nothing.
  const undo = useCallback(() => {
    dispatch({ type: "UNDO" });
  }, []);

  const redo = useCallback(() => {
    dispatch({ type: "REDO" });
  }, []);

  return {
    state,
    dispatch,
    initFromScenes,
    initFromComposition,
    addClip,
    removeClip,
    reorderClips,
    trimClip,
    moveClip,
    setClipVolume,
    selectClip,
    addSubtitle,
    addOverlayAtPlayhead,
    updateSubtitle,
    removeSubtitle,
    selectSubtitle,
    updateAllSubtitleStyles,
    applyCompositionTemplate,
    // V2 overlay actions
    addTextOverlay,
    addTextOverlayAtPlayhead,
    addStarterTextOverlay,
    addOverlayDirect,
    addBackgroundOverlayAtPlayhead,
    addImageBackgroundOverlayAtPlayhead,
    updateOverlay,
    removeOverlay,
    selectOverlay,
    selectVideo,
    selectLetterbox,
    clearAllSelections,
    reorderOverlay,
    setPlayhead,
    setPlaying,
    dispatchPlaybackEvent,
    setZoom,
    setInPoint,
    setOutPoint,
    setRazorMode,
    splitSubtitle,
    splitOverlay,
    splitClip,
    splitAtPlayhead,
    markClean,
    updateVideoPosition,
    updateVideoScale,
    updateVideoRotation,
    setVideoOutline,
    setVideoShadow,
    reorderLayer,
    setLetterbox,
    pushHistory,
    pushSnapshot,
    undo,
    redo,
  };
}
