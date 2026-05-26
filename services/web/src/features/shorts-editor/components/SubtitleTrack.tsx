"use client";

import { useCallback } from "react";
import type { EditorSubtitle, HistoryEntry } from "../lib/types";
import { computeTrackLaneWidth, pixelsToMs } from "../lib/timeline-math";
import { DEFAULT_SUBTITLE_STYLE, DEFAULT_SUBTITLE_DURATION_MS } from "../constants";
import { generateSubtitleId } from "../hooks/useEditorState";
import type { SnapPoint } from "../lib/snap";
import { SubtitleBlock } from "./SubtitleBlock";

interface SubtitleTrackProps {
  subtitles: EditorSubtitle[];
  zoom: number;
  totalDurationMs: number;
  playheadMs: number;
  selectedSubtitleIndex: number | null;
  onSelectSubtitle: (index: number | null) => void;
  onUpdateSubtitle: (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => void;
  onAddSubtitle: (subtitle: EditorSubtitle) => void;
  // Clicking a subtitle block snaps the playhead to its start (2026-05-18).
  onSeek?: (ms: number) => void;
  // Undo plumbing — forwarded to SubtitleBlock so time-drag gestures
  // push a history entry that Ctrl+Z can roll back.
  onPushHistory?: (entry: HistoryEntry) => void;
  // figma: 1669:154010 (펼침) / 1669:49002 (접힘) — zoom 변동 시 자막 섹션 펼침/접힘
  expanded?: boolean;
  // Magnetic snap targets (T4 second half). Forwarded straight to
  // SubtitleBlock so each block can resolve snap during a drag.
  snapPoints?: SnapPoint[];
  razorMode?: boolean;
  onRazorSplitSubtitle?: (index: number, atMs: number) => void;
  // B12 (2026-05-26) — lane background widens to at least this so the
  // lane stays painted across the full ruler extent when the content
  // is shorter than the visible scroll viewport. Omit for a content-
  // only width (the historical behaviour).
  containerWidthPx?: number;
}

export function SubtitleTrack({
  subtitles,
  zoom,
  totalDurationMs,
  selectedSubtitleIndex,
  onSelectSubtitle,
  onUpdateSubtitle,
  onAddSubtitle,
  onSeek,
  onPushHistory,
  snapPoints,
  razorMode = false,
  onRazorSplitSubtitle,
  containerWidthPx,
}: SubtitleTrackProps) {
  // B12 (2026-05-26): clamp the lane background to at least the
  // container's visible width so a short clip doesn't leave the lane
  // blank past totalDurationMs while the ruler keeps extending tick
  // labels out. Block positions are still computed off
  // ``msToPixels(startMs)`` — this only widens the painted lane.
  const totalWidth = computeTrackLaneWidth(totalDurationMs, zoom, containerWidthPx);

  const handleTrackDoubleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (e.target !== e.currentTarget) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const clickMs = Math.max(0, Math.round(pixelsToMs(x, zoom)));

      onAddSubtitle({
        id: generateSubtitleId(),
        text: "",
        startMs: clickMs,
        endMs: clickMs + DEFAULT_SUBTITLE_DURATION_MS,
        style: { ...DEFAULT_SUBTITLE_STYLE },
      });
    },
    [zoom, onAddSubtitle],
  );

  return (
    <div className="relative">
      {/* Track with blocks. Track height locked to h-12 regardless of zoom
          per 2026-05-18 review — the operator expected only the
          horizontal extent of the lane to react to zoom out, not the
          vertical thickness of the subtitle row. The earlier
          expanded ? "h-12" : "h-8" switch was visually shrinking the
          row on zoom-out. ``expanded`` prop is kept on the interface so
          callers don't break but no longer drives layout. */}
      <div
        data-testid="subtitle-lane"
        className="relative h-12 bg-grayscale-10"
        style={{ width: totalWidth }}
        onDoubleClick={handleTrackDoubleClick}
      >
        {/* Subtitle blocks */}
        {subtitles.map((sub, index) => (
          <SubtitleBlock
            key={sub.id}
            subtitle={sub}
            index={index}
            zoom={zoom}
            isSelected={selectedSubtitleIndex === index}
            onSelect={() => onSelectSubtitle(index)}
            onUpdate={onUpdateSubtitle}
            onSeek={onSeek}
            onPushHistory={onPushHistory}
            snapPoints={snapPoints}
            razorMode={razorMode}
            onRazorSplit={onRazorSplitSubtitle ? (atMs) => onRazorSplitSubtitle(index, atMs) : undefined}
          />
        ))}
      </div>
    </div>
  );
}
