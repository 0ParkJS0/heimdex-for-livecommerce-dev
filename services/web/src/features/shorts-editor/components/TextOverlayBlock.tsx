"use client";

// Timeline strip block for operator-added text overlays.
//
// Mirrors SubtitleBlock's "useEvent" ref pattern so a drag survives
// parent re-renders triggered by the onUpdate it dispatches — the bug
// SubtitleBlock fixed on 2026-05-19 applies verbatim here (parent
// re-renders → callback identity changes → useEffect cleanup tears
// down the document listener mid-drag).
//
// Differences vs SubtitleBlock:
//   * dispatches updateOverlay(id, {startMs, endMs}) instead of
//     updateSubtitle(index, ...). Text overlays are addressed by id
//     because the underlying state.overlays array can be reordered.
//   * snapshot history entry kind is overlay_transform-shape: the
//     reducer treats startMs/endMs changes as snapshot-worthy by the
//     same path it uses for transform edits, so the operator can
//     Ctrl+Z a trim or move in one stroke.
//   * lives inside a fixed-height 44px row that's already part of the
//     scrollbar-hidden track stack; we don't manage row height here.

import { useCallback, useEffect, useRef } from "react";

import { cn } from "@/lib/utils";
import { msToPixels, pixelsToMs } from "../lib/timeline-math";
import { getSnapThresholdMs, resolveSnap, type SnapPoint } from "../lib/snap";
import type { HistoryEntry } from "../lib/types";

interface TextOverlayBlockProps {
  overlayId: string;
  text: string;
  startMs: number;
  endMs: number;
  zoom: number;
  isSelected: boolean;
  onSelect: () => void;
  onUpdate: (id: string, updates: { startMs?: number; endMs?: number }) => void;
  onSeek?: (ms: number) => void;
  onPushHistory?: (entry: HistoryEntry) => void;
  // Magnetic snap targets (T4). Full timeline list; block filters its
  // own edges out at drag time via sourceId === overlayId. Optional so
  // host subtitle-track callers that don't surface snapping can skip.
  snapPoints?: SnapPoint[];
  // Cross-track row swap (L2). Called on pointerup when the operator's
  // vertical drag exceeds the row-swap threshold. ``count`` is the
  // number of slots to traverse — multi-row drags dispatch a single
  // higher count instead of N individual calls so the caller can
  // batch into one snapshot history entry.
  onReorder?: (id: string, direction: "forward" | "backward", count: number) => void;
}

// Row height of the timeline overlay strip (44px per row, matching
// the figma 2015:247122 chip height). Used as the displacement unit
// for cross-track drag — rounding to the nearest row count keeps the
// gesture predictable.
const OVERLAY_ROW_HEIGHT_PX = 44;

export function TextOverlayBlock({
  overlayId,
  text,
  startMs,
  endMs,
  zoom,
  isSelected,
  onSelect,
  onUpdate,
  onSeek,
  onPushHistory,
  snapPoints,
  onReorder,
}: TextOverlayBlockProps) {
  const leftPx = msToPixels(startMs, zoom);
  // Same 2px gutter as SubtitleBlock so back-to-back overlays don't
  // visually merge at minimum zoom. 8px floor preserves clickability.
  const rawWidthPx = msToPixels(endMs - startMs, zoom);
  const widthPx = Math.max(rawWidthPx - 2, 8);

  const draggingRef = useRef<"move" | "start" | "end" | null>(null);
  const startXRef = useRef(0);
  // Vertical-axis tracking for cross-track row swap (L2). startY is
  // captured on pointerdown; latestY tracks the most recent pointermove
  // so pointerup can compute the total displacement without subscribing
  // to a separate document listener.
  const startYRef = useRef(0);
  const latestYRef = useRef(0);
  const startValuesRef = useRef({ startMs: 0, endMs: 0 });
  // Tracks how many layerIndex steps have been committed during the
  // current drag. handleMove updates this; the diff against the new
  // computed delta drives the next reorder dispatch so the row change
  // is visible LIVE (OpenCut's `updateActiveDrag` pattern).
  const appliedRowDeltaRef = useRef(0);

  // Mirror the latest dispatch + zoom + snap points into refs so the
  // document pointermove handler always reads fresh values without
  // re-subscribing on each render. snapPoints flows in fresh each
  // render (it's built upstream from current state), so the ref lets
  // the in-flight drag see snap points added/removed during the drag
  // (e.g., playhead moves) without rebuilding listeners.
  const onUpdateRef = useRef(onUpdate);
  const zoomRef = useRef(zoom);
  const idRef = useRef(overlayId);
  const snapPointsRef = useRef(snapPoints);
  const onReorderRef = useRef(onReorder);
  useEffect(() => {
    onUpdateRef.current = onUpdate;
    zoomRef.current = zoom;
    idRef.current = overlayId;
    snapPointsRef.current = snapPoints;
    onReorderRef.current = onReorder;
  });

  const handlePointerDown = useCallback(
    (mode: "move" | "start" | "end") => (e: React.PointerEvent) => {
      e.stopPropagation();
      // Pre-gesture snapshot for Ctrl+Z. Pushes an overlay_time entry
      // so undo restores only the timing window (mirrors subtitle_time
      // for host subtitles).
      onPushHistory?.({
        kind: "overlay_time",
        id: overlayId,
        startMs,
        endMs,
      });
      draggingRef.current = mode;
      startXRef.current = e.clientX;
      startYRef.current = e.clientY;
      latestYRef.current = e.clientY;
      startValuesRef.current = { startMs, endMs };
      // Row-delta tracking so handleMove can commit the layerIndex
      // change LIVE (OpenCut's element-interaction pattern). Without
      // this, the row swap only fires on pointerup, which reads as
      // 'nothing happened' during the drag.
      appliedRowDeltaRef.current = 0;

      const handleMove = (ev: PointerEvent) => {
        if (!draggingRef.current) return;
        // Track the latest Y so pointerup can compute the row-swap
        // displacement without a separate document listener.
        latestYRef.current = ev.clientY;
        const dx = ev.clientX - startXRef.current;
        const z = zoomRef.current;
        const deltaMs = pixelsToMs(dx, z);
        const { startMs: s0, endMs: e0 } = startValuesRef.current;
        const id = idRef.current;
        const update = onUpdateRef.current;

        // Snap candidates excluding the dragging block's own edges so
        // an overlay doesn't snap to itself mid-gesture.
        const candidates = (snapPointsRef.current ?? []).filter(
          (p) => p.sourceId !== id,
        );
        const thresholdMs = getSnapThresholdMs(z);

        if (draggingRef.current === "move") {
          const rawStart = Math.max(0, Math.round(s0 + deltaMs));
          const duration = e0 - s0;
          // Move snaps the leading edge — the anchor the operator visually
          // tracks. If the trailing edge happens to land on a snap point
          // it's incidental (a future refinement could pick whichever
          // edge is closer; OpenCut does this with a tie-breaker).
          const snapped = resolveSnap(rawStart, candidates, thresholdMs);
          const newStart = snapped?.ms ?? rawStart;
          update(id, { startMs: newStart, endMs: newStart + duration });
          // Cross-track row commit, LIVE. Compute the desired
          // layerIndex delta from the current cursor Y and dispatch
          // only the DIFF against what we've already applied so the
          // reducer fires at most once per row crossing during the
          // drag (OpenCut's updateActiveDrag pattern).
          const dy = ev.clientY - startYRef.current;
          // dy < 0 (cursor up) → +layerIndex (forward / higher row).
          // dy > 0 (cursor down) → -layerIndex (backward / lower row).
          const desiredDelta = -Math.round(dy / OVERLAY_ROW_HEIGHT_PX);
          const diff = desiredDelta - appliedRowDeltaRef.current;
          if (diff !== 0) {
            const reorder = onReorderRef.current;
            if (reorder) {
              const direction = diff > 0 ? "forward" : "backward";
              reorder(id, direction, Math.abs(diff));
            }
            appliedRowDeltaRef.current = desiredDelta;
          }
        } else if (draggingRef.current === "start") {
          const rawStart = Math.max(0, Math.round(s0 + deltaMs));
          const snapped = resolveSnap(rawStart, candidates, thresholdMs);
          const newStart = snapped?.ms ?? rawStart;
          if (newStart < e0 - 100) {
            update(id, { startMs: newStart });
          }
        } else if (draggingRef.current === "end") {
          const rawEnd = Math.max(s0 + 100, Math.round(e0 + deltaMs));
          const snapped = resolveSnap(rawEnd, candidates, thresholdMs);
          const newEnd = snapped?.ms ?? rawEnd;
          // Re-clamp after snap so the snap target can't violate the
          // 100ms-min-duration invariant.
          update(id, { endMs: Math.max(s0 + 100, newEnd) });
        }
      };

      const handleUp = () => {
        // Row commits are dispatched live in handleMove (OpenCut
        // updateActiveDrag pattern); pointerup just tears down the
        // listeners.
        draggingRef.current = null;
        document.removeEventListener("pointermove", handleMove);
        document.removeEventListener("pointerup", handleUp);
      };

      document.addEventListener("pointermove", handleMove);
      document.addEventListener("pointerup", handleUp);
    },
    [overlayId, startMs, endMs, onPushHistory],
  );

  return (
    <div
      className={cn(
        // Figma 2015:247122 — operator text overlay chips:
        //   selected:  bg-heimdex-navy-500 (z-10)
        //   default:   bg-heimdex-navy-300, brightness on hover
        "group absolute bottom-1 top-1 flex items-center overflow-hidden rounded-[10px]",
        // Selected uses navy-100 (lighter highlight) per figma
        // 2047:408685 redesign — matches the host-subtitle selection
        // treatment so both tracks share visual language.
        isSelected
          ? "z-10 bg-heimdex-navy-100 text-grayscale-900"
          : "bg-heimdex-navy-300 hover:brightness-110",
      )}
      style={{ left: leftPx, width: widthPx }}
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
        onSeek?.(startMs);
      }}
    >
      <div
        className="absolute bottom-1 left-0 top-1 z-20 w-2 cursor-col-resize after:absolute after:bottom-0 after:left-[3px] after:top-0 after:w-[2px] after:rounded-full after:bg-white/0 after:transition-colors hover:after:bg-white/70"
        onPointerDown={handlePointerDown("start")}
        aria-label="텍스트 시작 시간 조정"
      />

      <div
        className="flex-1 min-w-0 cursor-grab select-none px-[10px] py-[12px] active:cursor-grabbing"
        onPointerDown={handlePointerDown("move")}
      >
        {widthPx >= 20 && (
          <p
            className={cn(
              "truncate text-[14px] font-semibold leading-[1.4] tracking-[-0.35px]",
              isSelected ? "text-grayscale-900" : "text-white",
            )}
          >
            {text || "텍스트"}
          </p>
        )}
      </div>

      <div
        className="absolute bottom-1 right-0 top-1 z-20 w-2 cursor-col-resize after:absolute after:bottom-0 after:right-[3px] after:top-0 after:w-[2px] after:rounded-full after:bg-white/0 after:transition-colors hover:after:bg-white/70"
        aria-label="텍스트 종료 시간 조정"
        onPointerDown={handlePointerDown("end")}
      />
    </div>
  );
}
