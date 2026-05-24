"use client";

import { useRef, useCallback } from "react";
import { cn } from "@/lib/utils";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import type { EditorClip } from "../lib/types";
import { msToPixels, pixelsToMs, getClipDuration, formatTimelineTimestamp } from "../lib/timeline-math";
import { useClipTrim } from "../hooks/useClipTrim";
import { getSnapThresholdMs, resolveSnap, type SnapPoint } from "../lib/snap";

// Single uniform dark surface; per-clip identity comes from the thumbnail.
const CLIP_BLOCK_BG = "bg-grayscale-800";

interface ClipBlockProps {
  clip: EditorClip;
  index: number;
  zoom: number;
  isSelected: boolean;
  onSelect: () => void;
  onTrim: (index: number, trimStartMs?: number, trimEndMs?: number) => void;
  onMove?: (index: number, timelineStartMs: number) => void;
  // Magnetic snap targets for drag-to-reposition. Built by ClipTrack
  // from neighbor clip edges + playhead + composition boundaries so
  // the clip can latch onto natural alignment points. The dragging
  // clip's own edges are excluded upstream via excludeId.
  snapPoints?: SnapPoint[];
  razorMode?: boolean;
  onRazorSplit?: (atMs: number) => void;
}

const FRAME_MS = 1000 / 30;

export function ClipBlock({
  clip,
  index,
  zoom,
  isSelected,
  onSelect,
  onTrim,
  onMove,
  snapPoints,
  razorMode = false,
  onRazorSplit,
}: ClipBlockProps) {
  const { onTrimStartDown, onTrimEndDown } = useClipTrim({
    clip,
    clipIndex: index,
    zoom,
    onTrim,
    snapPoints,
  });

  // Horizontal drag to reposition the clip on the timeline.
  const dragRef = useRef<{
    startX: number;
    origTimelineStartMs: number;
  } | null>(null);

  const onDragPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (!onMove) return;
      e.stopPropagation();
      e.preventDefault();
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      dragRef.current = {
        startX: e.clientX,
        origTimelineStartMs: clip.timelineStartMs,
      };
    },
    [clip.timelineStartMs, onMove],
  );

  const onDragPointerMove = useCallback(
    (e: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag || !onMove) return;
      const dx = e.clientX - drag.startX;
      const deltaMs = pixelsToMs(dx, zoom);
      let newStart = Math.max(0, Math.round(drag.origTimelineStartMs + deltaMs));
      // Magnetic snap — try the clip's start edge first, then its end
      // edge. Whichever lands within threshold wins. Adopting the
      // matched offset shifts BOTH edges together so the clip stays
      // rigid (duration is preserved during a move).
      if (snapPoints && snapPoints.length > 0) {
        const threshold = getSnapThresholdMs(zoom);
        const duration = clip.trimEndMs - clip.trimStartMs;
        const startSnap = resolveSnap(newStart, snapPoints, threshold);
        const endSnap = resolveSnap(newStart + duration, snapPoints, threshold);
        const startDist = startSnap ? Math.abs(newStart - startSnap.ms) : Infinity;
        const endDist = endSnap ? Math.abs(newStart + duration - endSnap.ms) : Infinity;
        if (startSnap && startDist <= endDist) {
          newStart = Math.max(0, startSnap.ms);
        } else if (endSnap) {
          newStart = Math.max(0, endSnap.ms - duration);
        }
      }
      onMove(index, newStart);
    },
    [index, zoom, onMove, snapPoints, clip.trimEndMs, clip.trimStartMs],
  );

  const onDragPointerUp = useCallback(
    (e: PointerEvent) => {
      if (!dragRef.current) return;
      (e.target as HTMLElement)?.releasePointerCapture?.(e.pointerId);
      dragRef.current = null;
      document.removeEventListener("pointermove", onDragPointerMove);
      document.removeEventListener("pointerup", onDragPointerUp);
    },
    [onDragPointerMove],
  );

  const handleDragDown = useCallback(
    (e: React.PointerEvent) => {
      if (!onMove) return;
      onDragPointerDown(e);
      document.addEventListener("pointermove", onDragPointerMove);
      document.addEventListener("pointerup", onDragPointerUp);
    },
    [onDragPointerDown, onDragPointerMove, onDragPointerUp, onMove],
  );

  const widthPx = msToPixels(getClipDuration(clip), zoom);
  const leftPx = msToPixels(clip.timelineStartMs, zoom);
  const durationSec = (getClipDuration(clip) / 1000).toFixed(1);

  const style: React.CSSProperties = {
    left: leftPx,
    width: Math.max(widthPx, 4),
  };

  return (
    <div
      className={cn(
        // figma 1669:49034 selected: border-2 border-white r-8 + inner 3px×35px white pill at each edge
        "group absolute bottom-1 top-1 flex cursor-pointer overflow-hidden rounded-[8px] transition-shadow",
        isSelected
          ? "z-10 border-2 border-white shadow-lg"
          : "border border-neutral-h-400/40 hover:border-neutral-h-400/80",
        CLIP_BLOCK_BG,
      )}
      style={style}
      onClick={(e) => {
        if (razorMode && onRazorSplit) {
          const rect = e.currentTarget.getBoundingClientRect();
          const offsetPx = e.clientX - rect.left;
          const rawMs = clip.timelineStartMs + (offsetPx / rect.width) * (clip.trimEndMs - clip.trimStartMs);
          const atMs = Math.round(rawMs / FRAME_MS) * FRAME_MS;
          onRazorSplit(atMs);
        } else {
          onSelect();
        }
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onSelect(); }}
    >
      {/* Thumbnail strip backdrop (figma 638:17616) — 80-px sections
          repeated across the clip width with a `#9d9d9d` right border
          on each, giving the operator a sense of how many keyframe
          chunks the clip covers without paying for real thumbnail
          renders per chunk. Painted via repeating-linear-gradient so
          we render a single absolutely-positioned div regardless of
          clip width. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "repeating-linear-gradient(to right, transparent 0, transparent 79px, rgba(157,157,157,0.5) 79px, rgba(157,157,157,0.5) 80px)",
        }}
      />

      {/* Left trim handle + figma white vertical pill when selected */}
      <div
        className="absolute left-0 top-0 bottom-0 z-20 w-2 cursor-col-resize bg-white/40 opacity-0 transition-opacity group-hover:opacity-100 hover:!opacity-100"
        onPointerDown={onTrimStartDown}
      >
        <div className="absolute left-0.5 top-1/2 -translate-y-1/2 h-6 w-0.5 rounded-full bg-white" />
      </div>
      {isSelected && (
        <span
          aria-hidden
          className="pointer-events-none absolute left-[6px] top-1/2 z-10 h-[35px] w-[3px] -translate-y-1/2 rounded-[100px] bg-white"
        />
      )}

      {/* Drag handle area (center content) — horizontal drag to
          reposition the clip on the timeline. */}
      <div
        className="flex-1 min-w-0 flex items-center gap-1.5 px-2 overflow-hidden cursor-grab active:cursor-grabbing"
        onPointerDown={onMove ? handleDragDown : undefined}
      >
        {/* Thumbnail (only show if clip is wide enough) */}
        {widthPx > 60 && (
          <div className="h-8 w-12 flex-shrink-0 overflow-hidden rounded-sm pointer-events-none">
            <SceneThumbnail
              videoId={clip.videoId}
              sceneId={clip.sceneId}
              agentAvailable={clip.sourceType !== "gdrive"}
              className="h-full w-full object-cover"
            />
          </div>
        )}

        {/* Label */}
        {widthPx > 40 && (
          <div className="min-w-0 flex-1 pointer-events-none">
            {clip.label && widthPx > 80 ? (
              <>
                <p className="truncate text-[10px] font-medium leading-tight text-white">
                  {clip.label}
                </p>
                <p className="truncate text-[9px] leading-tight text-white/70">
                  {durationSec}s
                </p>
              </>
            ) : (
              <>
                <p className="truncate text-[10px] font-medium leading-tight text-white">
                  {durationSec}s
                </p>
                {widthPx > 100 && (
                  <p className="truncate text-[9px] leading-tight text-white/70">
                    {formatTimelineTimestamp(clip.trimStartMs)}
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* Right trim handle + figma white vertical pill when selected */}
      <div
        className="absolute right-0 top-0 bottom-0 z-20 w-2 cursor-col-resize bg-white/40 opacity-0 transition-opacity group-hover:opacity-100 hover:!opacity-100"
        onPointerDown={onTrimEndDown}
      >
        <div className="absolute right-0.5 top-1/2 -translate-y-1/2 h-6 w-0.5 rounded-full bg-white" />
      </div>
      {isSelected && (
        <span
          aria-hidden
          className="pointer-events-none absolute right-[6px] top-1/2 z-10 h-[35px] w-[3px] -translate-y-1/2 rounded-[100px] bg-white"
        />
      )}
    </div>
  );
}
