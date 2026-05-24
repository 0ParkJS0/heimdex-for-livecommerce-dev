"use client";

import { useCallback } from "react";
import type { EditorSubtitle, HistoryEntry } from "../lib/types";
import { msToPixels, pixelsToMs } from "../lib/timeline-math";
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
}: SubtitleTrackProps) {
  const totalWidth = msToPixels(totalDurationMs, zoom);

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
