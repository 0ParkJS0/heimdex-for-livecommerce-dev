"use client";

import { useRef, useEffect, useCallback } from "react";
import type { EditorClip, EditorSubtitle } from "../lib/types";
import { msToPixels } from "../lib/timeline-math";
import { MIN_ZOOM, MAX_ZOOM } from "../constants";
import { TimelineRuler } from "./TimelineRuler";
import { ClipTrack } from "./ClipTrack";
import { SubtitleTrack } from "./SubtitleTrack";
import { PlayheadCursor } from "./PlayheadCursor";

interface TimelinePanelProps {
  clips: EditorClip[];
  subtitles: EditorSubtitle[];
  zoom: number;
  playheadMs: number;
  isPlaying: boolean;
  totalDurationMs: number;
  selectedClipIndex: number | null;
  selectedSubtitleIndex: number | null;
  onSelectClip: (index: number | null) => void;
  onSelectSubtitle: (index: number | null) => void;
  onTrimClip: (index: number, trimStartMs?: number, trimEndMs?: number) => void;
  onReorderClips: (fromIndex: number, toIndex: number) => void;
  onUpdateSubtitle: (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => void;
  onAddSubtitle: (subtitle: EditorSubtitle) => void;
  onSeek: (ms: number) => void;
  onZoomChange: (zoom: number) => void;
}

function ZoomInIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m6-6H6" />
    </svg>
  );
}

function ZoomOutIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M18 12H6" />
    </svg>
  );
}

export function TimelinePanel({
  clips,
  subtitles,
  zoom,
  playheadMs,
  isPlaying,
  totalDurationMs,
  selectedClipIndex,
  selectedSubtitleIndex,
  onSelectClip,
  onSelectSubtitle,
  onTrimClip,
  onReorderClips,
  onUpdateSubtitle,
  onAddSubtitle,
  onSeek,
  onZoomChange,
}: TimelinePanelProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const trackHeight = 120; // ruler (24px) + clip track (48px) + subtitle track (32px) + padding

  // Auto-scroll to follow playhead during playback
  useEffect(() => {
    if (!isPlaying || !scrollContainerRef.current) return;

    const container = scrollContainerRef.current;
    const playheadPx = msToPixels(playheadMs, zoom);
    const containerWidth = container.clientWidth;
    const scrollLeft = container.scrollLeft;

    if (playheadPx > scrollLeft + containerWidth * 0.8) {
      container.scrollLeft = playheadPx - containerWidth * 0.3;
    }
    if (playheadPx < scrollLeft) {
      container.scrollLeft = Math.max(0, playheadPx - 20);
    }
  }, [playheadMs, isPlaying, zoom]);

  const handleZoomIn = useCallback(() => {
    onZoomChange(Math.min(MAX_ZOOM, zoom + 25));
  }, [zoom, onZoomChange]);

  const handleZoomOut = useCallback(() => {
    onZoomChange(Math.max(MIN_ZOOM, zoom - 25));
  }, [zoom, onZoomChange]);

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex h-8 flex-shrink-0 items-center justify-between border-b border-gray-300 bg-gray-100 px-3">
        <span className="text-[10px] font-medium text-gray-500">타임라인</span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={handleZoomOut}
            disabled={zoom <= MIN_ZOOM}
            className="rounded p-0.5 text-gray-500 hover:bg-gray-200 hover:text-gray-700 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <ZoomOutIcon />
          </button>
          <span className="w-8 text-center text-[10px] text-gray-500">{zoom}%</span>
          <button
            type="button"
            onClick={handleZoomIn}
            disabled={zoom >= MAX_ZOOM}
            className="rounded p-0.5 text-gray-500 hover:bg-gray-200 hover:text-gray-700 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <ZoomInIcon />
          </button>
        </div>
      </div>

      {/* Scrollable timeline area */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-x-auto overflow-y-hidden"
      >
        <div className="relative" style={{ minWidth: "100%" }}>
          {/* Ruler */}
          <TimelineRuler totalDurationMs={totalDurationMs} zoom={zoom} />

          {/* Clip track */}
          <ClipTrack
            clips={clips}
            zoom={zoom}
            selectedClipIndex={selectedClipIndex}
            totalDurationMs={totalDurationMs}
            onSelectClip={onSelectClip}
            onTrimClip={onTrimClip}
            onReorderClips={onReorderClips}
            onSeek={onSeek}
          />

          {/* Subtitle track */}
          <SubtitleTrack
            subtitles={subtitles}
            zoom={zoom}
            totalDurationMs={totalDurationMs}
            playheadMs={playheadMs}
            selectedSubtitleIndex={selectedSubtitleIndex}
            onSelectSubtitle={onSelectSubtitle}
            onUpdateSubtitle={onUpdateSubtitle}
            onAddSubtitle={onAddSubtitle}
          />

          {/* Playhead cursor — spans ruler + all tracks */}
          <PlayheadCursor
            playheadMs={playheadMs}
            zoom={zoom}
            height={trackHeight}
            onSeek={onSeek}
          />
        </div>
      </div>
    </div>
  );
}
