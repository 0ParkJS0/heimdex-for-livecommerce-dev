"use client";

import { useRef, useState, useCallback, useEffect } from "react";
import { ChevronsUpDown, X as XIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { EditorClip, EditorState, EditorSubtitle, HistoryEntry, LayerOrderId, Playback, PlaybackEvent } from "../lib/types";
import type { EditorOverlay } from "../lib/overlay-types";
import { OverlayRenderer } from "./preview/OverlayRenderer";
import { SubtitleCancelActionBar } from "./SubtitleCancelActionBar";
import { getActiveSubtitles, getVisibleSubtitles } from "../lib/source-time";
import { formatTimelineTimestamp } from "../lib/timeline-math";
import { resolveFontFamily } from "@/lib/fonts";
import { usePlaybackSync } from "../hooks/usePlaybackSync";
import { getThumbnailAspectClass, type ThumbnailAspectRatio } from "@/lib/thumbnailUtils";

// Floor for the inverse-scale applied to resize/rotation handles so they keep
// a constant px size while the video wrapper scales. Guards against 1/0 (and
// absurd magnification) when the video scale `vs` approaches zero.
const MIN_INVERSE_SCALE = 0.01;

interface PreviewPanelProps {
  clips: EditorClip[];
  subtitles: EditorSubtitle[];
  // V2 overlays — rendered alongside subtitles. Empty for V1 sessions.
  overlays?: EditorOverlay[];
  selectedOverlayId?: string | null;
  onSelectOverlay?: (id: string | null) => void;
  // V2 update callback — used for drag (transform.x/y) and resize
  // (fontSizePx for text, transform.widthPx/heightPx for background).
  onUpdateOverlay?: (id: string, updates: Partial<EditorOverlay>) => void;
  // figma 1669:49437 — element selection action bar fires these to delete
  // the currently selected V2 overlay / V1 subtitle. Optional so existing
  // callers don't break; the bar simply hides when omitted.
  onRemoveOverlay?: (id: string) => void;
  onRemoveSubtitle?: (index: number) => void;
  playheadMs: number;
  playback: Playback;
  totalDurationMs: number;
  selectedSubtitleIndex: number | null;
  onPlayheadChange: (ms: number) => void;
  dispatchPlaybackEvent: (event: PlaybackEvent) => void;
  onSelectSubtitle: (index: number | null) => void;
  onUpdateSubtitlePosition: (index: number, positionX: number, positionY: number) => void;
  onUpdateSubtitleFontSize: (index: number, fontSizePx: number) => void;
  // PR 7 — drag the dedicated video layer around the canvas. ``x``/``y``
  // are normalized [0, 1] anchors (0.5/0.5 = centered, the default
  // position before any drag). ``scale`` defaults to 1. Optional so
  // embedded preview tiles that don't surface dragging stay untouched.
  //
  // ``outline`` is the operator-added border drawn around the video
  // frame via CSS ``outline`` (NOT ``border`` — outline doesn't
  // affect layout so width changes can't shift the video element).
  videoTransform?: {
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
  onUpdateVideoPosition?: (x: number, y: number) => void;
  onUpdateVideoScale?: (scale: number) => void;
  onUpdateVideoRotation?: (rotationDeg: number) => void;
  // 2026-05-24 — selection-based routing for the background panel.
  // ``selectedVideo`` / ``selectedLetterbox`` drive the preview ring,
  // and the matching click handlers dispatch the selection to the
  // reducer. All four are optional so embedded preview tiles
  // (FullscreenOverlay etc.) can skip the selection plumbing without
  // breaking the type contract.
  selectedVideo?: boolean;
  selectedLetterbox?: boolean;
  onSelectVideo?: (active: boolean) => void;
  onSelectLetterbox?: (active: boolean) => void;
  // Clears every selection slot in one dispatch — wired to the empty
  // canvas click so the operator can deselect by clicking the
  // background of the preview.
  onClearSelections?: () => void;
  // Unified z-order. When provided, each layer is rendered with a zIndex
  // derived from its position in the array (bottom=0 → top=length-1).
  // When absent, the pre-layerOrder hard-coded stacking applies.
  layerOrder?: LayerOrderId[];
  // PR 3 remainder — global letterbox bars. Rendered above subtitles
  // (D12). Operators drag the ChevronsUpDown handles on the inner edges
  // to resize each bar's height. Optional so embedded preview tiles
  // that don't surface editing stay untouched.
  letterbox?: EditorState["letterbox"];
  onUpdateLetterbox?: (letterbox: EditorState["letterbox"]) => void;
  // Undo plumbing — preview captures a pre-gesture snapshot on each
  // drag/resize/rotate pointerdown so Ctrl+Z can roll one step back.
  // Optional so existing callers (e.g. embedded preview tiles that
  // don't surface dragging) don't break.
  onPushHistory?: (entry: HistoryEntry) => void;
  // 2026-05-26 — fullscreen now means "this same PreviewPanel
  // instance scales up to fill the viewport"; the separate
  // FullscreenOverlay component was removed because mounting a
  // second <video> element raced the inline one's src/load and left
  // the fullscreen surface on a black, silent frame whenever
  // hydration timing didn't line up. Keeping one video element and
  // flipping the wrapper to ``fixed inset-0`` instead means
  // src/currentTime never get touched on toggle, so the
  // operator-reported "fullscreen has no image and no sound" path
  // can't happen by construction. ``onCloseFullscreen`` is the
  // ESC + chrome-close callback; required when ``fullscreen`` is
  // true so the operator can exit. ``filename`` shows above the
  // close button so the operator knows which short they're viewing.
  fullscreen?: boolean;
  onCloseFullscreen?: () => void;
  filename?: string;
}

function PlayIcon() {
  return (
    <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
    </svg>
  );
}

export function PreviewPanel({
  clips,
  subtitles,
  overlays = [],
  selectedOverlayId = null,
  onSelectOverlay,
  onUpdateOverlay,
  onRemoveOverlay,
  onRemoveSubtitle,
  playheadMs,
  playback,
  totalDurationMs,
  selectedSubtitleIndex,
  onPlayheadChange,
  dispatchPlaybackEvent,
  onSelectSubtitle,
  onUpdateSubtitlePosition,
  onUpdateSubtitleFontSize,
  videoTransform,
  onUpdateVideoPosition,
  onUpdateVideoScale,
  onUpdateVideoRotation,
  layerOrder,
  letterbox,
  onUpdateLetterbox,
  onPushHistory,
  selectedVideo = false,
  selectedLetterbox = false,
  onSelectVideo,
  onSelectLetterbox,
  onClearSelections,
  fullscreen = false,
  onCloseFullscreen,
  filename,
}: PreviewPanelProps) {
  const isPlaying = playback.kind === "playing";

  // ESC closes the fullscreen surface — only attached while in
  // fullscreen so the editor's other ESC handlers (e.g. dialog
  // dismiss) keep working normally outside this mode.
  useEffect(() => {
    if (!fullscreen || !onCloseFullscreen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseFullscreen();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [fullscreen, onCloseFullscreen]);

  const {
    videoRef,
    preloadRef,
    togglePlay,
    onSeeked,
    onEnded,
  } = usePlaybackSync({
    clips,
    playheadMs,
    playback,
    onPlayheadChange,
    dispatchPlaybackEvent,
  });

  // The shorts editor canvas is always 9:16 (vertical reels/shorts output);
  // the org-wide thumbnail_aspect_ratio setting governs other surfaces.
  const aspectRatio: ThumbnailAspectRatio = "9:16";

  const visibleSubtitles = getVisibleSubtitles(subtitles, clips);
  const activeSubtitles = getActiveSubtitles(visibleSubtitles, playheadMs);
  const progressPct = totalDurationMs > 0 ? (playheadMs / totalDurationMs) * 100 : 0;

  const containerRef = useRef<HTMLDivElement>(null);
  const [isHovering, setIsHovering] = useState(false);
  const showTransport = isHovering || isPlaying;
  const dragRef = useRef<{
    mode: "move" | "resize";
    subtitleIndex: number;
    startX: number;
    startY: number;
    origX: number;
    origY: number;
    origFontSizePx: number;
    lockedWidth: number | null;
  } | null>(null);

  // V2 overlay drag state — separate from V1 dragRef so the two paths
  // don't step on each other when a session has both populated.
  // The third mode ``rotate`` captures the angle at pointerdown
  // (startAngleRad) and the overlay's original rotationDeg so
  // pointermove can apply the delta around the overlay's center.
  const overlayDragRef = useRef<{
    mode: "move" | "resize" | "rotate";
    overlayId: string;
    overlayKind: "text" | "background";
    startX: number;
    startY: number;
    origX: number;
    origY: number;
    origFontSizePx: number;
    origWidthPx: number;
    origHeightPx: number;
    origRotationDeg: number;
    startAngleRad: number;
  } | null>(null);

  // PR 7 — drag the dedicated <video> layer. Independent of dragRef /
  // overlayDragRef so a video drag doesn't clobber an in-flight overlay
  // gesture (and vice versa). Same normalized-anchor model as overlays:
  // origX/origY are the videoTransform values at pointerdown, the
  // pointermove handler reads dx/dy in container coords and clamps
  // back into [0, 1].
  const videoDragRef = useRef<{
    startX: number;
    startY: number;
    origX: number;
    origY: number;
  } | null>(null);

  // Video scale — 4-corner handles, radial-distance model matching the
  // overlay resize path. origScale and startDist captured at
  // pointerdown so the same pointermove logic applies regardless of
  // which corner the operator grabbed.
  const videoResizeRef = useRef<{
    startDist: number;
    origScale: number;
    centerX: number;
    centerY: number;
  } | null>(null);

  // Video rotation — start angle captured at pointerdown so the
  // pointermove can apply (currentAngle - startAngle) on top of
  // origRotationDeg. Same model as the overlay rotate path.
  const videoRotateRef = useRef<{
    centerX: number;
    centerY: number;
    startAngleRad: number;
    origRotationDeg: number;
  } | null>(null);

  // PR 3 — letterbox bar drag. ``edge`` records which bar's height the
  // operator is resizing. ``startY`` is the clientY at pointerdown,
  // ``origPct`` is the bar's height before the gesture so pointermove
  // can apply a delta in canvas-percent terms.
  const letterboxDragRef = useRef<{
    edge: "top" | "bottom";
    startY: number;
    origPct: number;
  } | null>(null);

  const getSubtitleIndex = useCallback((subtitleId: string): number => {
    return subtitles.findIndex((s) => s.id === subtitleId);
  }, [subtitles]);

  const handleMovePointerDown = useCallback((e: React.PointerEvent, sub: EditorSubtitle) => {
    e.preventDefault();
    e.stopPropagation();
    const idx = getSubtitleIndex(sub.id);
    if (idx < 0) return;

    // Snapshot the pre-gesture style so Ctrl+Z can restore position
    // (and any other style fields that incidentally changed) in one
    // step. Pushed on pointerdown so the very first pointermove
    // already has an entry to roll back to.
    onPushHistory?.({ kind: "subtitle_style", index: idx, style: { ...sub.style } });

    onSelectSubtitle(idx);
    (e.target as HTMLElement).setPointerCapture(e.pointerId);

    // Lock the element width to prevent reflow during drag
    const el = (e.target as HTMLElement).closest("[data-subtitle-box]") as HTMLElement | null;
    const lockedWidth = el ? el.offsetWidth : null;

    dragRef.current = {
      mode: "move",
      subtitleIndex: idx,
      startX: e.clientX,
      startY: e.clientY,
      origX: sub.style.positionX,
      origY: sub.style.positionY,
      origFontSizePx: sub.style.fontSizePx,
      lockedWidth,
    };
  }, [getSubtitleIndex, onSelectSubtitle, onPushHistory]);

  const handleResizePointerDown = useCallback((e: React.PointerEvent, sub: EditorSubtitle) => {
    e.preventDefault();
    e.stopPropagation();
    const idx = getSubtitleIndex(sub.id);
    if (idx < 0) return;

    // Snapshot the pre-gesture style so Ctrl+Z restores fontSizePx
    // (and incidentally position) in one step. Pushed on pointerdown
    // for the same reason as the move path above.
    onPushHistory?.({ kind: "subtitle_style", index: idx, style: { ...sub.style } });

    (e.target as HTMLElement).setPointerCapture(e.pointerId);

    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const centerX = rect.left + sub.style.positionX * rect.width;
    const centerY = rect.top + sub.style.positionY * rect.height;
    const startDist = Math.hypot(e.clientX - centerX, e.clientY - centerY);

    dragRef.current = {
      mode: "resize",
      subtitleIndex: idx,
      startX: startDist, // reuse startX to store initial distance
      startY: 0,
      origX: sub.style.positionX,
      origY: sub.style.positionY,
      origFontSizePx: sub.style.fontSizePx,
      lockedWidth: null,
    };
  }, [getSubtitleIndex]);

  // PR 7 — pointerdown on the dedicated video layer. Mirrors the
  // overlay-move path: snapshot the pre-gesture position into history
  // (so Ctrl+Z can roll the drag back as one stroke) and capture the
  // pointer so the cursor doesn't lose tracking when it leaves the
  // canvas mid-drag.
  const handleVideoPointerDown = useCallback(
    (e: React.PointerEvent<HTMLVideoElement>) => {
      if (!onUpdateVideoPosition) return;
      const current = videoTransform ?? { x: 0.5, y: 0.5 };
      e.stopPropagation();
      onPushHistory?.({
        kind: "video_position",
        x: current.x,
        y: current.y,
      });
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      videoDragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        origX: current.x,
        origY: current.y,
      };
    },
    [videoTransform, onUpdateVideoPosition, onPushHistory],
  );

  // PR 3 — pointerdown on a letterbox ChevronsUpDown handle. The
  // operator clicks the handle that sits flush on the bar's inner
  // edge and drags vertically to resize that bar's height. Top bar
  // grows downward, bottom bar grows upward, so deltaY has the
  // opposite sign for each.
  const handleLetterboxHandlePointerDown = useCallback(
    (edge: "top" | "bottom") => (e: React.PointerEvent) => {
      if (!letterbox || !onUpdateLetterbox) return;
      e.stopPropagation();
      onPushHistory?.({ kind: "letterbox", letterbox });
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      letterboxDragRef.current = {
        edge,
        startY: e.clientY,
        origPct:
          edge === "top" ? letterbox.topHeightPct : letterbox.bottomHeightPct,
      };
    },
    [letterbox, onUpdateLetterbox, onPushHistory],
  );

  const handleVideoResizePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!onUpdateVideoScale) return;
      e.preventDefault();
      e.stopPropagation();
      const currentScale = videoTransform?.scale ?? 1;
      onPushHistory?.({ kind: "video_scale", scale: currentScale });
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const cx = rect.left + (videoTransform?.x ?? 0.5) * rect.width;
      const cy = rect.top + (videoTransform?.y ?? 0.5) * rect.height;
      videoResizeRef.current = {
        startDist: Math.hypot(e.clientX - cx, e.clientY - cy),
        origScale: currentScale,
        centerX: cx,
        centerY: cy,
      };
    },
    [videoTransform, onUpdateVideoScale, onPushHistory],
  );

  const handleVideoRotatePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!onUpdateVideoRotation) return;
      e.preventDefault();
      e.stopPropagation();
      const currentRotation = videoTransform?.rotationDeg ?? 0;
      onPushHistory?.({ kind: "video_rotation", rotationDeg: currentRotation });
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const cx = rect.left + (videoTransform?.x ?? 0.5) * rect.width;
      const cy = rect.top + (videoTransform?.y ?? 0.5) * rect.height;
      videoRotateRef.current = {
        centerX: cx,
        centerY: cy,
        startAngleRad: Math.atan2(e.clientY - cy, e.clientX - cx),
        origRotationDeg: currentRotation,
      };
    },
    [videoTransform, onUpdateVideoRotation, onPushHistory],
  );

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();

    // PR 3 — letterbox bar drag (resize via ChevronsUpDown handle).
    const lDrag = letterboxDragRef.current;
    if (lDrag && letterbox && onUpdateLetterbox) {
      const deltaPct = ((e.clientY - lDrag.startY) / rect.height) * 100;
      // Top bar: drag down → grow (positive delta). Bottom bar: drag
      // up → grow (negative delta becomes positive growth).
      const growth = lDrag.edge === "top" ? deltaPct : -deltaPct;
      const nextPct = Math.max(0, Math.min(50, lDrag.origPct + growth));
      onUpdateLetterbox(
        lDrag.edge === "top"
          ? { ...letterbox, topHeightPct: nextPct }
          : { ...letterbox, bottomHeightPct: nextPct },
      );
    }

    // PR 7 — video layer drag. Same normalized model as overlays:
    // delta is fraction-of-container, clamped to [0, 1]. Shift-axis
    // lock reuses the same heuristic so the affordance is consistent
    // across video / overlay / subtitle drags.
    const vDrag = videoDragRef.current;
    if (vDrag && onUpdateVideoPosition) {
      let deltaX = (e.clientX - vDrag.startX) / rect.width;
      let deltaY = (e.clientY - vDrag.startY) / rect.height;
      if (e.shiftKey) {
        if (Math.abs(deltaX) >= Math.abs(deltaY)) {
          deltaY = 0;
        } else {
          deltaX = 0;
        }
      }
      const newX = Math.max(0, Math.min(1, vDrag.origX + deltaX));
      const newY = Math.max(0, Math.min(1, vDrag.origY + deltaY));
      onUpdateVideoPosition(newX, newY);
    }

    // Video scale resize -----------------------------------------------
    const vResize = videoResizeRef.current;
    if (vResize && onUpdateVideoScale) {
      const currentDist = Math.hypot(
        e.clientX - vResize.centerX,
        e.clientY - vResize.centerY,
      );
      if (vResize.startDist >= 1) {
        const next = Math.max(0.1, Math.min(10, vResize.origScale * (currentDist / vResize.startDist)));
        onUpdateVideoScale(next);
      }
    }

    // Video rotation ----------------------------------------------------
    const vRot = videoRotateRef.current;
    if (vRot && onUpdateVideoRotation) {
      const currentAngleRad = Math.atan2(
        e.clientY - vRot.centerY,
        e.clientX - vRot.centerX,
      );
      const deltaRad = currentAngleRad - vRot.startAngleRad;
      const deltaDeg = (deltaRad * 180) / Math.PI;
      const next = vRot.origRotationDeg + deltaDeg;
      const clamped = Math.max(-360, Math.min(360, next));
      // Shift-rotate magnetic snap — same window as the overlay rotate
      // path so the UX matches across video / overlay rotation.
      let snapped = clamped;
      if (e.shiftKey) {
        const nearestMultiple = Math.round(clamped / 90) * 90;
        if (Math.abs(clamped - nearestMultiple) <= 5) {
          snapped = nearestMultiple;
        }
      }
      onUpdateVideoRotation(snapped);
    }

    // V1 subtitle drag --------------------------------------------------
    const drag = dragRef.current;
    if (drag) {
      if (drag.mode === "move") {
        let deltaX = (e.clientX - drag.startX) / rect.width;
        let deltaY = (e.clientY - drag.startY) / rect.height;
        // Shift-drag axis lock: when the user holds Shift while
        // moving, keep the motion on whichever axis they're currently
        // pushing harder on. Computed per-frame (not at gesture
        // start) so the lock can flip mid-drag if the user releases
        // Shift, swings the other direction, and re-presses Shift.
        if (e.shiftKey) {
          if (Math.abs(deltaX) >= Math.abs(deltaY)) {
            deltaY = 0;
          } else {
            deltaX = 0;
          }
        }
        const newX = Math.max(0, Math.min(1, drag.origX + deltaX));
        const newY = Math.max(0, Math.min(1, drag.origY + deltaY));
        onUpdateSubtitlePosition(drag.subtitleIndex, newX, newY);
      } else {
        const centerX = rect.left + drag.origX * rect.width;
        const centerY = rect.top + drag.origY * rect.height;
        const currentDist = Math.hypot(e.clientX - centerX, e.clientY - centerY);
        const initialDist = drag.startX; // stored initial distance
        if (initialDist >= 1) {
          const scale = currentDist / initialDist;
          const newSize = Math.round(Math.max(8, Math.min(200, drag.origFontSizePx * scale)));
          onUpdateSubtitleFontSize(drag.subtitleIndex, newSize);
        }
      }
    }

    // V2 overlay drag --------------------------------------------------
    const ovDrag = overlayDragRef.current;
    if (ovDrag) {
      const overlay = overlays.find((o) => o.id === ovDrag.overlayId);
      if (!overlay || !onUpdateOverlay) return;

      if (ovDrag.mode === "move") {
        let deltaX = (e.clientX - ovDrag.startX) / rect.width;
        let deltaY = (e.clientY - ovDrag.startY) / rect.height;
        // Shift-drag axis lock — see the V1 path above for rationale.
        if (e.shiftKey) {
          if (Math.abs(deltaX) >= Math.abs(deltaY)) {
            deltaY = 0;
          } else {
            deltaX = 0;
          }
        }
        const newX = Math.max(0, Math.min(1, ovDrag.origX + deltaX));
        const newY = Math.max(0, Math.min(1, ovDrag.origY + deltaY));
        onUpdateOverlay(ovDrag.overlayId, {
          transform: { ...overlay.transform, x: newX, y: newY },
        } as Partial<EditorOverlay>);
      } else if (ovDrag.mode === "rotate") {
        // Compute the cursor's current angle around the overlay
        // center and add the delta against the angle captured at
        // pointerdown. Clamp to the TransformProps invariant
        // [-360, 360]; users that want a continuous spin can drag
        // again from the wrapped value.
        const centerX = rect.left + ovDrag.origX * rect.width;
        const centerY = rect.top + ovDrag.origY * rect.height;
        const currentAngleRad = Math.atan2(
          e.clientY - centerY,
          e.clientX - centerX,
        );
        const deltaRad = currentAngleRad - ovDrag.startAngleRad;
        const deltaDeg = (deltaRad * 180) / Math.PI;
        const next = ovDrag.origRotationDeg + deltaDeg;
        const clamped = Math.max(-360, Math.min(360, next));
        // Shift-rotate magnetic snap: when the cursor lands within ±5°
        // of a 90° multiple, pull the angle onto that multiple so the
        // user feels a slight "catch". Outside the window the rotation
        // stays free, matching the operator's "약간 걸리는 느낌" cue.
        const SNAP_WINDOW_DEG = 5;
        let snapped = clamped;
        if (e.shiftKey) {
          const nearestMultiple = Math.round(clamped / 90) * 90;
          if (Math.abs(clamped - nearestMultiple) <= SNAP_WINDOW_DEG) {
            snapped = nearestMultiple;
          }
        }
        onUpdateOverlay(ovDrag.overlayId, {
          transform: {
            ...overlay.transform,
            rotationDeg: snapped,
          },
        } as Partial<EditorOverlay>);
      } else {
        const centerX = rect.left + ovDrag.origX * rect.width;
        const centerY = rect.top + ovDrag.origY * rect.height;
        const currentDist = Math.hypot(e.clientX - centerX, e.clientY - centerY);
        const initialDist = ovDrag.startX;
        if (initialDist >= 1) {
          const scale = currentDist / initialDist;
          if (ovDrag.overlayKind === "text") {
            const newSize = Math.round(
              Math.max(8, Math.min(200, ovDrag.origFontSizePx * scale)),
            );
            onUpdateOverlay(ovDrag.overlayId, {
              fontSizePx: newSize,
            } as Partial<EditorOverlay>);
          } else {
            const newW = Math.round(Math.max(10, Math.min(10000, ovDrag.origWidthPx * scale)));
            const newH = Math.round(Math.max(10, Math.min(10000, ovDrag.origHeightPx * scale)));
            onUpdateOverlay(ovDrag.overlayId, {
              transform: {
                ...overlay.transform,
                widthPx: newW,
                heightPx: newH,
              },
            } as Partial<EditorOverlay>);
          }
        }
      }
    }
  }, [onUpdateSubtitlePosition, onUpdateSubtitleFontSize, onUpdateOverlay, onUpdateVideoPosition, onUpdateVideoScale, onUpdateLetterbox, letterbox, overlays]);

  const handlePointerUp = useCallback(() => {
    dragRef.current = null;
    overlayDragRef.current = null;
    videoDragRef.current = null;
    videoResizeRef.current = null;
    videoRotateRef.current = null;
    letterboxDragRef.current = null;
  }, []);

  // V2 overlay handlers — body drag = move, corner drag = resize.
  // Selection happens on pointerdown so a drag-without-click still
  // updates the panel selection mid-gesture.
  const handleOverlayMovePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>, overlay: EditorOverlay) => {
      e.preventDefault();
      e.stopPropagation();
      // Snapshot the pre-gesture transform so Ctrl+Z restores the
      // overlay position in one step. Move only changes transform.x/y
      // so an overlay_transform entry covers the gesture.
      onPushHistory?.({
        kind: "overlay_transform",
        id: overlay.id,
        transform: { ...overlay.transform },
      });
      onSelectOverlay?.(overlay.id);
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      overlayDragRef.current = {
        mode: "move",
        overlayId: overlay.id,
        overlayKind: overlay.kind,
        startX: e.clientX,
        startY: e.clientY,
        origX: overlay.transform.x,
        origY: overlay.transform.y,
        origFontSizePx:
          overlay.kind === "text" ? overlay.fontSizePx : 0,
        origWidthPx: overlay.transform.widthPx ?? 0,
        origHeightPx: overlay.transform.heightPx ?? 0,
        origRotationDeg: overlay.transform.rotationDeg,
        startAngleRad: 0,
      };
    },
    [onSelectOverlay, onPushHistory],
  );

  const handleOverlayResizePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>, overlay: EditorOverlay) => {
      e.preventDefault();
      e.stopPropagation();
      // Resize updates transform.widthPx/heightPx (background) AND
      // fontSizePx (text). Push both kinds so a single Ctrl+Z reverts
      // the whole gesture in one stroke. Pop order is LIFO so the
      // font-size entry lands first when the operator hits Ctrl+Z
      // (which matches the gesture's "first effect").
      if (overlay.kind === "text") {
        onPushHistory?.({
          kind: "overlay_font_size",
          id: overlay.id,
          fontSizePx: overlay.fontSizePx,
        });
      }
      onPushHistory?.({
        kind: "overlay_transform",
        id: overlay.id,
        transform: { ...overlay.transform },
      });
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const centerX = rect.left + overlay.transform.x * rect.width;
      const centerY = rect.top + overlay.transform.y * rect.height;
      const startDist = Math.hypot(e.clientX - centerX, e.clientY - centerY);
      overlayDragRef.current = {
        mode: "resize",
        overlayId: overlay.id,
        overlayKind: overlay.kind,
        startX: startDist, // reuse startX to store initial radial distance
        startY: 0,
        origX: overlay.transform.x,
        origY: overlay.transform.y,
        origFontSizePx:
          overlay.kind === "text" ? overlay.fontSizePx : 0,
        origWidthPx: overlay.transform.widthPx ?? 0,
        origHeightPx: overlay.transform.heightPx ?? 0,
        origRotationDeg: overlay.transform.rotationDeg,
        startAngleRad: 0,
      };
    },
    [onPushHistory],
  );

  // Corner-outer rotate: caller fires this when a pointerdown lands on
  // the small rotate handle just outside each resize corner. We snap
  // the starting angle (cursor → overlay center) into the ref so
  // pointermove can apply a delta around the center.
  const handleOverlayRotatePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>, overlay: EditorOverlay) => {
      e.preventDefault();
      e.stopPropagation();
      // Snapshot the pre-gesture transform — rotate only changes
      // transform.rotationDeg but we snapshot the whole transform so
      // the undo path is uniform with move/resize.
      onPushHistory?.({
        kind: "overlay_transform",
        id: overlay.id,
        transform: { ...overlay.transform },
      });
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const centerX = rect.left + overlay.transform.x * rect.width;
      const centerY = rect.top + overlay.transform.y * rect.height;
      const startAngleRad = Math.atan2(
        e.clientY - centerY,
        e.clientX - centerX,
      );
      overlayDragRef.current = {
        mode: "rotate",
        overlayId: overlay.id,
        overlayKind: overlay.kind,
        startX: 0,
        startY: 0,
        origX: overlay.transform.x,
        origY: overlay.transform.y,
        origFontSizePx:
          overlay.kind === "text" ? overlay.fontSizePx : 0,
        origWidthPx: overlay.transform.widthPx ?? 0,
        origHeightPx: overlay.transform.heightPx ?? 0,
        origRotationDeg: overlay.transform.rotationDeg,
        startAngleRad,
      };
    },
    [onPushHistory],
  );

  return (
    <div
      className={cn(
        "relative h-full w-full",
        // 2026-05-26 — fullscreen wraps the SAME preview surface in a
        // fixed viewport-filling shell so the video element + its
        // usePlaybackSync wiring stay mounted across the toggle. No
        // new <video>, no src race, no black-frame-on-open.
        fullscreen &&
          "fixed inset-0 z-50 flex flex-col items-center justify-center bg-black p-4",
      )}
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
    >
      {fullscreen && (
        <>
          {filename && (
            <div
              data-testid="preview-fullscreen-filename"
              className="pointer-events-none absolute left-4 top-4 z-10 max-w-[60%] truncate text-sm font-semibold text-white"
            >
              {filename}
            </div>
          )}
          <button
            type="button"
            onClick={onCloseFullscreen}
            aria-label="전체화면 닫기"
            data-testid="preview-fullscreen-close"
            className="absolute right-4 top-4 z-10 inline-flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
          >
            <XIcon className="h-5 w-5" />
          </button>
        </>
      )}
      {/* Preview container — figma 1602:37722: shorts canvas fills the card
          surface so the editor center is the 9:16 stage with no padding. */}
      <div
        ref={containerRef}
        // ``container-type: size`` opts this surface into CSS
        // container queries so overlays inside can size themselves
        // with ``cqw`` / ``cqh`` units relative to the actual preview
        // dimensions. Overlay fontSize / width / height are stored in
        // 720-tall output coords and re-scaled at render time —
        // see OverlayRenderer + the V1 subtitle span below.
        style={{ containerType: "size" }}
        className={cn(
          "relative overflow-hidden bg-black",
          aspectRatio === "9:16"
            ? fullscreen
              ? // 9:16 fills the viewport height; width follows the
                // 9:16 ratio so the short shape stays exact.
                "h-full max-h-full aspect-[9/16]"
              : "h-full w-full"
            : fullscreen
              ? "aspect-video w-full max-w-[626px] rounded-[10px]"
              : "aspect-video w-full max-w-[480px] rounded-[10px]",
        )}
        onClick={() => {
          // Empty-canvas click — clear every selection slot so the
          // operator can "deselect" by clicking the background of the
          // preview. Prefer onClearSelections when wired (one dispatch
          // path); fall back to the per-slot clears for embedded
          // surfaces that only surface the legacy handlers.
          if (onClearSelections) {
            onClearSelections();
          } else {
            onSelectSubtitle(null);
            onSelectOverlay?.(null);
          }
        }}
      >
        {/* Main video element — kept as its own dedicated layer (NOT
            folded into the overlay array) but exposes drag + scale
            affordances via handleVideoPointerDown / handleVideoResizePointerDown.
            scale() applies uniform scaling around the element centre;
            translate() offsets from the centred (0.5/0.5) default. */}
        {(() => {
          const vx = videoTransform?.x ?? 0.5;
          const vy = videoTransform?.y ?? 0.5;
          const vs = videoTransform?.scale ?? 1;
          const vRot = videoTransform?.rotationDeg ?? 0;
          const vOutline = videoTransform?.outline ?? null;
          const vShadow = videoTransform?.shadow ?? null;
          const videoZIndex = layerOrder
            ? layerOrder.findIndex((l) => l.kind === "video")
            : undefined;
          // CSS ``filter: drop-shadow`` follows the alpha mask of the
          // element so the shadow hugs the <video> rectangle (and any
          // outline drawn around it). spreadPx has no direct CSS
          // counterpart — we stack multiple drop-shadow layers when
          // spread > 0 to fake the "grow" effect, matching what
          // OverlayRenderer does for text/background overlays.
          const dropShadowCss = vShadow
            ? (() => {
                const layers: string[] = [];
                const spread = Math.max(0, vShadow.spreadPx);
                // Single layer for spread == 0; otherwise stack a few
                // copies at small offset increments along the same
                // direction so the silhouette appears "thicker".
                const layerCount = spread > 0 ? Math.min(8, 1 + Math.floor(spread / 4)) : 1;
                for (let i = 0; i < layerCount; i += 1) {
                  layers.push(
                    `drop-shadow(${vShadow.offsetX}px ${vShadow.offsetY}px ${vShadow.blurPx}px ${vShadow.color})`,
                  );
                }
                return layers.join(" ");
              })()
            : undefined;
          // 2026-05-24 — selection ring uses Tailwind's ``ring-inset``
          // so it sits inside the <video> bounds without pushing the
          // element. ``ring-2`` matches overlay/subtitle selection
          // rings (heimdex-navy-500). The existing CSS ``outline`` for
          // the operator-added 윤곽선 sits OUTSIDE the box, so the two
          // don't collide visually.
          // 2026-05-25 — wrapper-transform pattern so the 4 resize
          // handles and the rotation handle ride the video's actual
          // visual bbox, not the static canvas inset. Previously the
          // wrapper was ``absolute inset-0`` (canvas-sized) and only
          // the <video> received the transform — the handles stayed
          // glued to the canvas corners as the video shrunk. Now the
          // wrapper itself carries the scale/translate/rotate transform
          // so its children (the video AND the corner/rotation handles)
          // all move together with the video. Handles add an inverse
          // ``scale(1/vs)`` so they stay constant px size while their
          // anchor (transformOrigin) keeps them pinned to the matching
          // video corner / top edge.
          return (
            <div
              className="absolute inset-0"
              style={{
                ...(videoZIndex != null ? { zIndex: videoZIndex } : {}),
                transform: `scale(${vs}) translate(${(vx - 0.5) * 100}%, ${(vy - 0.5) * 100}%) rotate(${vRot}deg)`,
                transformOrigin: "center center",
                // ``filter: drop-shadow`` applied on the wrapper so the
                // shadow includes the operator-added outline; if
                // applied on the <video> itself the outline would sit
                // OUTSIDE the shadow source rect and not pick up the
                // drop.
                ...(dropShadowCss ? { filter: dropShadowCss } : {}),
              }}
            >
              <video
                ref={videoRef}
                className={cn(
                  "h-full w-full object-contain",
                  onUpdateVideoPosition && "cursor-grab active:cursor-grabbing",
                  selectedVideo &&
                    "ring-2 ring-heimdex-navy-500 ring-inset",
                )}
                style={{
                  // CSS ``outline`` instead of ``border`` so the line
                  // doesn't push the video element when the operator
                  // dials the width — the outline sits OUTSIDE the
                  // element's box without affecting layout.
                  ...(vOutline && vOutline.widthPx > 0
                    ? { outline: `${vOutline.widthPx}px solid ${vOutline.color}` }
                    : {}),
                }}
                playsInline
                onSeeked={onSeeked}
                onEnded={onEnded}
                onPointerDown={onUpdateVideoPosition ? handleVideoPointerDown : undefined}
                onPointerMove={onUpdateVideoPosition ? handlePointerMove : undefined}
                onPointerUp={onUpdateVideoPosition ? handlePointerUp : undefined}
                onClick={
                  onSelectVideo
                    ? (e) => {
                        // Selecting the host video element dispatches
                        // SELECT_VIDEO(true) and clears every other
                        // selection slot via the reducer's mutex
                        // semantics. stopPropagation prevents the
                        // outer empty-canvas click from immediately
                        // clearing the selection.
                        e.stopPropagation();
                        onSelectVideo(true);
                      }
                    : undefined
                }
              />
              {/* 4-corner scale handles + rotation handle — only when
                  the operator has the video selected, mirroring the
                  overlay selection affordance so the UX matches across
                  the canvas. Each corner uses the standard nesw/nwse
                  cursor pair. The rotation handle sits just outside
                  the top edge so it doesn't overlap the resize dot. */}
              {onUpdateVideoScale && selectedVideo && (
                <>
                  {(["nw", "ne", "sw", "se"] as const).map((corner) => (
                    <div
                      key={corner}
                      className={cn(
                        "absolute z-10 h-3 w-3 rounded-full border-2 border-white bg-heimdex-navy-500",
                        corner === "nw" && "-top-1.5 -left-1.5 cursor-nwse-resize",
                        corner === "ne" && "-top-1.5 -right-1.5 cursor-nesw-resize",
                        corner === "sw" && "-bottom-1.5 -left-1.5 cursor-nesw-resize",
                        corner === "se" && "-bottom-1.5 -right-1.5 cursor-nwse-resize",
                      )}
                      style={{
                        // Inverse-scale so the handle stays a constant
                        // px size while the wrapper scales the video.
                        // transform-origin anchors the handle to the
                        // matching corner so the -1.5px offset still
                        // sits on the actual video edge after the
                        // 1/vs scale.
                        transform: `scale(${1 / Math.max(vs, MIN_INVERSE_SCALE)})`,
                        transformOrigin:
                          corner === "nw"
                            ? "top left"
                            : corner === "ne"
                              ? "top right"
                              : corner === "sw"
                                ? "bottom left"
                                : "bottom right",
                      }}
                      onPointerDown={handleVideoResizePointerDown}
                      onPointerMove={handlePointerMove}
                      onPointerUp={handlePointerUp}
                    />
                  ))}
                  {onUpdateVideoRotation && (
                    <div
                      aria-label="비디오 회전"
                      className="absolute -top-7 left-1/2 z-10 h-3 w-3 cursor-grab rounded-full border-2 border-white bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.15)]"
                      style={{
                        // Bottom-center origin pins the handle to the
                        // video's top edge after inverse-scale, mirroring
                        // OverlayRenderer's rotation-handle anchoring.
                        transform: `translateX(-50%) scale(${1 / Math.max(vs, MIN_INVERSE_SCALE)})`,
                        transformOrigin: "bottom center",
                      }}
                      onPointerDown={handleVideoRotatePointerDown}
                      onPointerMove={handlePointerMove}
                      onPointerUp={handlePointerUp}
                    />
                  )}
                </>
              )}
            </div>
          );
        })()}

        {/* Subtitle overlay */}
        {(() => {
          const subtitleZIndex = layerOrder
            ? layerOrder.findIndex((l) => l.kind === "subtitles")
            : undefined;
          return activeSubtitles.map((sub) => {
          const idx = getSubtitleIndex(sub.id);
          const isSelected = idx >= 0 && idx === selectedSubtitleIndex;
          const isDraggingThis = dragRef.current?.subtitleIndex === idx && dragRef.current?.mode === "move";

          return (
            <div
              key={sub.id}
              data-subtitle-box
              className={cn(
                "absolute",
                isSelected ? "cursor-grab" : "cursor-grab",
              )}
              style={{
                left: `${sub.style.positionX * 100}%`,
                top: `${sub.style.positionY * 100}%`,
                transform: "translate(-50%, -50%)",
                pointerEvents: "auto",
                // max-content prevents edge-wrapping during drag;
                // maxWidth 85% matches FullscreenOverlay so text wraps
                // identically on both surfaces.
                width: "max-content",
                maxWidth: "85%",
                ...(subtitleZIndex != null ? { zIndex: isSelected ? subtitleZIndex + 100 : subtitleZIndex } : { zIndex: isSelected ? 110 : 10 }),
                // During a drag, lock BOTH the explicit width AND
                // remove the percent-based maxWidth so the box can't
                // re-wrap to multi-line if the canvas dimensions change
                // (container query, ResizeObserver, transform clamp,
                // etc.) mid-drag. Without max-width:'none', a small
                // canvas re-measure can re-evaluate `maxWidth: 85%`
                // below the locked px width, forcing wrap and stretching
                // the box vertically — that was the '드래그 시 세로로
                // 길어짐' regression.
                ...(isDraggingThis && dragRef.current?.lockedWidth
                  ? {
                      width: `${dragRef.current.lockedWidth}px`,
                      maxWidth: "none",
                    }
                  : {}),
              }}
              onPointerDown={(e) => handleMovePointerDown(e, sub)}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onClick={(e) => e.stopPropagation()}
            >
              {sub.text === "" ? (
                <div
                  aria-label="empty text overlay placeholder"
                  className={cn(
                    "h-16 w-16 rounded bg-red-500",
                    isSelected && "ring-2 ring-heimdex-navy-500 ring-offset-1",
                  )}
                />
              ) : (
                <p
                  className={cn(
                    "whitespace-pre-wrap select-none text-center",
                    isSelected && "rounded ring-2 ring-heimdex-navy-500 ring-offset-1",
                  )}
                  style={{
                    fontFamily: resolveFontFamily(sub.style.fontFamily),
                    // 2026-05-20 — switched from a static 0.55 multiplier
                    // to a container-query scale. ``fontSizePx`` is stored
                    // in 720-tall output coords; the preview canvas
                    // (containerType: size set above) varies with viewport,
                    // so ``100cqh / 720`` resolves to whatever fraction of
                    // a px the current canvas height implies. The Math.max
                    // floor keeps tiny stored sizes legible (8px minimum
                    // displayed). Same formula used by OverlayRenderer +
                    // FullscreenOverlay so all three surfaces agree.
                    fontSize: `max(8px, calc(${sub.style.fontSizePx} * 100cqh / 720))`,
                    color: sub.style.fontColor,
                    fontWeight: sub.style.fontWeight,
                    textAlign: "center",
                    // Korean eojeol-aware wrapping: keep-all stops the
                    // glyph-by-glyph split that the browser default
                    // (break-all-ish behavior on CJK without explicit
                    // word boundaries) produces, and break-word lets
                    // truly oversized eojeols still wrap instead of
                    // overflowing the preview pill.
                    wordBreak: "keep-all",
                    overflowWrap: "break-word",
                    padding: "2px 6px",
                    borderRadius: "2px",
                    ...(sub.style.backgroundColor
                      ? {
                          backgroundColor: sub.style.backgroundColor,
                          opacity: sub.style.backgroundOpacity,
                        }
                      : {}),
                  }}
                >
                  {sub.text}
                </p>
              )}

              {/* Resize corner handles */}
              {isSelected && (
                <>
                  {(["nw", "ne", "sw", "se"] as const).map((corner) => (
                    <div
                      key={corner}
                      className={cn(
                        "absolute h-3 w-3 rounded-full bg-heimdex-navy-500 border-2 border-white",
                        corner === "nw" && "-top-1.5 -left-1.5 cursor-nwse-resize",
                        corner === "ne" && "-top-1.5 -right-1.5 cursor-nesw-resize",
                        corner === "sw" && "-bottom-1.5 -left-1.5 cursor-nesw-resize",
                        corner === "se" && "-bottom-1.5 -right-1.5 cursor-nwse-resize",
                      )}
                      onPointerDown={(e) => handleResizePointerDown(e, sub)}
                      onPointerMove={handlePointerMove}
                      onPointerUp={handlePointerUp}
                    />
                  ))}
                </>
              )}
            </div>
          );
        });
        })()}

        {/* V2 overlays — rendered above subtitles. The active-window check
            mirrors getActiveSubtitles: only show overlays whose [start, end)
            includes the current playhead. When layerOrder is present each
            overlay's zIndex is its position in the unified stack. */}
        {overlays
          .filter((o) => o.startMs <= playheadMs && playheadMs < o.endMs)
          .map((o) => {
            const overlayZIndex = layerOrder
              ? layerOrder.findIndex((l) => l.kind === "overlay" && l.id === o.id)
              : undefined;
            return (
              <OverlayRenderer
                key={o.id}
                overlay={o}
                isSelected={selectedOverlayId === o.id}
                zIndex={overlayZIndex != null && overlayZIndex >= 0 ? overlayZIndex : undefined}
                onClick={() => onSelectOverlay?.(o.id)}
                onMovePointerDown={(e) =>
                  handleOverlayMovePointerDown(e, o)
                }
                onResizePointerDown={(_corner, e) =>
                  handleOverlayResizePointerDown(e, o)
                }
                onRotatePointerDown={(_corner, e) =>
                  handleOverlayRotatePointerDown(e, o)
                }
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                onUpdateText={
                  o.kind === "text" && onUpdateOverlay
                    ? (next) => onUpdateOverlay(o.id, { text: next })
                    : undefined
                }
              />
            );
          })}

        {/* figma 1669:49437 — element selection action bar (선택 + content + trash) */}
        {(() => {
          const selectedOverlay = overlays.find((o) => o.id === selectedOverlayId);
          const selectedSubtitle =
            selectedSubtitleIndex != null && selectedSubtitleIndex < subtitles.length
              ? subtitles[selectedSubtitleIndex]
              : null;
          if (selectedOverlay && onRemoveOverlay) {
            const label =
              selectedOverlay.kind === "text"
                ? selectedOverlay.text
                : "단색 배경";
            return (
              <div
                className="absolute bottom-4 left-1/2 z-20 -translate-x-1/2"
                onClick={(e) => e.stopPropagation()}
              >
                <SubtitleCancelActionBar
                  text={label}
                  onRemove={() => onRemoveOverlay(selectedOverlay.id)}
                />
              </div>
            );
          }
          if (selectedSubtitle && onRemoveSubtitle && selectedSubtitleIndex != null) {
            return (
              <div
                className="absolute bottom-4 left-1/2 z-20 -translate-x-1/2"
                onClick={(e) => e.stopPropagation()}
              >
                <SubtitleCancelActionBar
                  text={selectedSubtitle.text}
                  onRemove={() => onRemoveSubtitle(selectedSubtitleIndex)}
                />
              </div>
            );
          }
          return null;
        })()}

        {/* No clips placeholder */}
        {clips.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-grayscale-500">
            <span className="text-xs">장면을 추가하세요</span>
          </div>
        )}

        {/* Letterbox bars. z-index derived from layerOrder when available;
            falls back to hard-coded z-[15] for surfaces without layerOrder. */}
        {letterbox && (
          <>
            {(() => {
              const lbZIndex = layerOrder
                ? layerOrder.findIndex((l) => l.kind === "letterbox")
                : 15;
              const lbZ = lbZIndex >= 0 ? lbZIndex : 15;
              return (
                <>
            {letterbox.topHeightPct > 0 && (
              <div
                // 2026-05-24 — letterbox bars are now clickable so the
                // operator can select them (selection-based routing).
                // ``pointer-events`` is auto only when onSelectLetterbox
                // is wired; embedded preview tiles without selection
                // keep the bar inert.
                className={cn(
                  "absolute left-0 right-0 top-0",
                  onSelectLetterbox ? "cursor-pointer" : "pointer-events-none",
                  selectedLetterbox && "ring-2 ring-heimdex-navy-500 ring-inset",
                )}
                style={{
                  height: `${letterbox.topHeightPct}%`,
                  backgroundColor: letterbox.fillColor,
                  zIndex: lbZ,
                  // Q4 — outline (윤곽선) on the inner edge of the
                  // top bar (i.e. the edge that touches the video).
                  // The outer edges are pinned to the canvas border
                  // so a border there would never be visible.
                  borderBottom:
                    letterbox.borderColor && letterbox.borderWidthPx > 0
                      ? `${letterbox.borderWidthPx}px solid ${letterbox.borderColor}`
                      : undefined,
                }}
                onClick={
                  onSelectLetterbox
                    ? (e) => {
                        e.stopPropagation();
                        onSelectLetterbox(true);
                      }
                    : undefined
                }
              />
            )}
            {letterbox.bottomHeightPct > 0 && (
              <div
                className={cn(
                  "absolute bottom-0 left-0 right-0",
                  onSelectLetterbox ? "cursor-pointer" : "pointer-events-none",
                  selectedLetterbox && "ring-2 ring-heimdex-navy-500 ring-inset",
                )}
                style={{
                  height: `${letterbox.bottomHeightPct}%`,
                  backgroundColor: letterbox.fillColor,
                  zIndex: lbZ,
                  borderTop:
                    letterbox.borderColor && letterbox.borderWidthPx > 0
                      ? `${letterbox.borderWidthPx}px solid ${letterbox.borderColor}`
                      : undefined,
                }}
                onClick={
                  onSelectLetterbox
                    ? (e) => {
                        e.stopPropagation();
                        onSelectLetterbox(true);
                      }
                    : undefined
                }
              />
            )}
            {onUpdateLetterbox && (
              <>
                {/* Top bar handle — sits centred on the bar's INNER
                    edge (y = topHeightPct%). When the bar is 0 the
                    operator can still drag from y=0 to introduce a
                    bar (no chrome would otherwise be reachable). */}
                <div
                  role="slider"
                  aria-label="레터박스 상단 높이 조정"
                  // 2026-05-22 operator review — drop the white pill +
                  // larger chevron so the affordance reads as a
                  // draggable grip, not a separate button. drop-shadow
                  // keeps the icon legible against any letterbox fill.
                  className="absolute left-1/2 -translate-x-1/2 -translate-y-1/2 cursor-ns-resize text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.6)]"
                  style={{ top: `${letterbox.topHeightPct}%`, zIndex: lbZ + 5 }}
                  onPointerDown={handleLetterboxHandlePointerDown("top")}
                  onPointerMove={handlePointerMove}
                  onPointerUp={handlePointerUp}
                >
                  <ChevronsUpDown className="h-6 w-6" strokeWidth={2.25} />
                </div>
                <div
                  role="slider"
                  aria-label="레터박스 하단 높이 조정"
                  className="absolute left-1/2 -translate-x-1/2 translate-y-1/2 cursor-ns-resize text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.6)]"
                  style={{ bottom: `${letterbox.bottomHeightPct}%`, zIndex: lbZ + 5 }}
                  onPointerDown={handleLetterboxHandlePointerDown("bottom")}
                  onPointerMove={handlePointerMove}
                  onPointerUp={handlePointerUp}
                >
                  <ChevronsUpDown className="h-6 w-6" strokeWidth={2.25} />
                </div>
              </>
            )}
                </>
              );
            })()}
          </>
        )}

        {/* Preload hidden video for next clip */}
        <video
          ref={preloadRef}
          className="hidden"
          preload="auto"
          muted
          playsInline
        />
      </div>

      {/* Transport controls — fade on idle, always shown while playing */}
      <div
        className={cn(
          "flex w-full flex-col gap-2 transition-opacity duration-200 max-w-[352px]",
          showTransport ? "opacity-100" : "pointer-events-none opacity-0",
        )}
      >
        {/* Progress bar */}
        <div className="relative h-1 w-full rounded-full bg-grayscale-200">
          <div
            className="absolute left-0 top-0 h-full rounded-full bg-heimdex-navy-500 transition-[width] duration-75"
            style={{ width: `${Math.min(100, progressPct)}%` }}
          />
        </div>

        {/* Play button + time display */}
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={togglePlay}
            disabled={clips.length === 0}
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-full transition-colors",
              clips.length > 0
                ? "bg-heimdex-navy-500 text-white hover:bg-heimdex-navy-600"
                : "cursor-not-allowed bg-grayscale-100 text-grayscale-400",
            )}
          >
            {isPlaying ? <PauseIcon /> : <PlayIcon />}
          </button>

          <span className="font-mono text-xs text-grayscale-500">
            {formatTimelineTimestamp(playheadMs)} / {formatTimelineTimestamp(totalDurationMs)}
          </span>
        </div>
      </div>
    </div>
  );
}
