"use client";

import { useCallback, useMemo } from "react";
import type { EditorClip, EditorSubtitle } from "../lib/types";
import { msToPixels, pixelsToMs } from "../lib/timeline-math";
import { ClipBlock } from "./ClipBlock";
import {
  boundarySnapPoints,
  clipEdgeSnapPoints,
  playheadSnapPoint,
  subtitleEdgeSnapPoints,
  type SnapPoint,
} from "../lib/snap";

interface ClipTrackProps {
  clips: EditorClip[];
  // Subtitle edges feed the snap source so a clip trim/move can latch
  // onto the start/end of a host subtitle. Optional so embedders
  // without subtitles still get clip-only snapping.
  subtitles?: EditorSubtitle[];
  zoom: number;
  selectedClipIndex: number | null;
  totalDurationMs: number;
  playheadMs: number;
  onSelectClip: (index: number | null) => void;
  onTrimClip: (index: number, trimStartMs?: number, trimEndMs?: number) => void;
  onMoveClip?: (index: number, timelineStartMs: number) => void;
  onSeek: (ms: number) => void;
  razorMode?: boolean;
  onRazorSplitClip?: (index: number, atMs: number) => void;
}

export function ClipTrack({
  clips,
  subtitles,
  zoom,
  selectedClipIndex,
  totalDurationMs,
  playheadMs,
  onSelectClip,
  onTrimClip,
  onMoveClip,
  onSeek,
  razorMode = false,
  onRazorSplitClip,
}: ClipTrackProps) {
  const totalWidth = msToPixels(totalDurationMs, zoom);

  // Shared snap targets — playhead + boundaries + every subtitle edge
  // (operator request: trim-edge should latch onto subtitle ends).
  // Per-clip snap source adds the OTHER clips' edges via ``excludeId``
  // so each dragging clip never snaps to itself.
  const baseSnapPoints: SnapPoint[] = useMemo(
    () => [
      playheadSnapPoint(playheadMs),
      ...boundarySnapPoints(totalDurationMs),
      ...subtitleEdgeSnapPoints(subtitles ?? []),
    ],
    [playheadMs, totalDurationMs, subtitles],
  );

  const handleTrackClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (e.target !== e.currentTarget) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const ms = pixelsToMs(x, zoom);
      onSeek(Math.max(0, Math.round(ms)));
      onSelectClip(null);
    },
    [zoom, onSeek, onSelectClip],
  );

  return (
    <div
      className="relative h-12"
      style={{ width: totalWidth }}
      onClick={handleTrackClick}
    >
      {/* Track label */}
      <div className="pointer-events-none absolute -left-0 top-0 z-10 flex h-full items-center">
        <span className="rounded-r bg-grayscale-800/60 px-1.5 py-0.5 text-[9px] font-medium text-grayscale-400">
          VIDEO
        </span>
      </div>

      {/* Clip blocks — positioned absolutely via timelineStartMs */}
      {clips.map((clip, index) => (
        <ClipBlock
          key={clip.id}
          clip={clip}
          index={index}
          zoom={zoom}
          isSelected={selectedClipIndex === index}
          onSelect={() => onSelectClip(index)}
          onTrim={onTrimClip}
          onMove={onMoveClip}
          snapPoints={[
            ...baseSnapPoints,
            ...clipEdgeSnapPoints(clips, { excludeId: clip.id }),
          ]}
          razorMode={razorMode}
          onRazorSplit={onRazorSplitClip ? (atMs) => onRazorSplitClip(index, atMs) : undefined}
        />
      ))}
    </div>
  );
}
