"use client";

// figma: 1669:48897 (default) / 1669:48312 (compressed) — timeline shell
// figma: 1669:153949 (toolbar row) — trash + timecode • transport • controls • zoom
import { useRef, useEffect, useCallback, useState, useMemo } from "react";
import { createPortal } from "react-dom";
import { Maximize, Pause, SquareSplitHorizontal, Trash2, Volume2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { EditorClip, EditorSubtitle, Playback, PlaybackRate } from "../lib/types";
import { msToPixels, formatVideoTimestampHMS } from "../lib/timeline-math";
import { TimelineRuler } from "./TimelineRuler";
import { ClipTrack } from "./ClipTrack";
import { SubtitleTrack } from "./SubtitleTrack";
import { TextOverlayBlock } from "./TextOverlayBlock";
import {
  boundarySnapPoints,
  clipEdgeSnapPoints,
  overlayEdgeSnapPoints,
  playheadSnapPoint,
  subtitleEdgeSnapPoints,
  type SnapPoint,
} from "../lib/snap";
import { PlayheadCursor } from "./PlayheadCursor";
import { TimelineZoomControl } from "./TimelineZoomControl";

interface TimelinePanelProps {
  clips: EditorClip[];
  subtitles: EditorSubtitle[];
  // Q7 — V2 text overlays render in a separate strip ABOVE the
  // existing subtitle track so 'host auto STT' subtitles and
  // 'operator-added text overlays' stay visually distinct. Passed as
  // an already-projected subtitle-shape array so SubtitleBlock-style
  // math reuses cleanly. Each entry carries layerIndex so the strip
  // can place rows by it (0 = bottom, increasing upward).
  textOverlaysForTimeline?: (EditorSubtitle & { layerIndex: number })[];
  onSelectTextOverlay?: (id: string | null) => void;
  selectedTextOverlayId?: string | null;
  // Trim / move dispatch for the upper overlay strip (Phase 3 T3).
  // SubtitleBlock-style drag handles call this with {startMs, endMs};
  // optional so embedded read-only timelines can skip wiring it.
  onUpdateTextOverlay?: (
    id: string,
    updates: { startMs?: number; endMs?: number },
  ) => void;
  // Cross-track row swap (L2). Called on the overlay's pointerup when
  // the operator's vertical drag exceeded the row-swap threshold.
  // ``count`` lets the caller batch multi-row drags into one bookkeeping
  // unit if desired; current wiring just calls the reducer N times.
  onReorderTextOverlay?: (
    id: string,
    direction: "forward" | "backward",
    count: number,
  ) => void;
  // L5 split-at-playhead — figma 2047:408589 adds a toolbar button
  // next to Maximize so operators have a clickable surface for the
  // razor, not just the S keyboard shortcut.
  onSplitAtPlayhead?: () => void;
  // Razor mode: button activates mode; block clicks fire the actual split.
  onActivateRazor?: () => void;
  razorMode?: boolean;
  onRazorSplitClip?: (index: number, atMs: number) => void;
  onRazorSplitSubtitle?: (index: number, atMs: number) => void;
  zoom: number;
  playheadMs: number;
  playback: Playback;
  totalDurationMs: number;
  selectedClipIndex: number | null;
  selectedSubtitleIndex: number | null;
  onSelectClip: (index: number | null) => void;
  onSelectSubtitle: (index: number | null) => void;
  onTrimClip: (index: number, trimStartMs?: number, trimEndMs?: number) => void;
  onMoveClip?: (index: number, timelineStartMs: number) => void;
  onReorderClips: (fromIndex: number, toIndex: number) => void;
  onUpdateSubtitle: (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => void;
  onAddSubtitle: (subtitle: EditorSubtitle) => void;
  onRemoveClip: (index: number) => void;
  onRemoveSubtitle: (index: number) => void;
  onTogglePlay: () => void;
  onSeek: (ms: number) => void;
  onZoomChange: (zoom: number) => void;
  playbackRate?: PlaybackRate;
  onPlaybackRateChange?: (rate: PlaybackRate) => void;
  // figma: 1670:185907 — volume + maximize controls
  volume?: number;
  onVolumeChange?: (volume: number) => void;
  onToggleFullscreen?: () => void;
  // Undo plumbing — forwarded to SubtitleTrack → SubtitleBlock so the
  // subtitle time-drag (move / start-edge / end-edge) gestures push a
  // history entry the editor's Ctrl+Z handler can roll back.
  onPushHistory?: (entry: import("../lib/types").HistoryEntry) => void;
}

// figma: 1669:153949 — toolbar buttons are 32×32 r-8 bg neutral-50.
const PILL_BUTTON =
  "flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] bg-neutral-h-50 text-neutral-h-800 transition-colors hover:bg-neutral-h-100 disabled:cursor-not-allowed disabled:opacity-30";

const PLAYBACK_OPTIONS: PlaybackRate[] = [8, 4, 2, 1];

function SpeedPopover({
  rate,
  onChange,
}: {
  rate: PlaybackRate;
  onChange?: (rate: PlaybackRate) => void;
}) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => onChange && setOpen((v) => !v)}
        disabled={!onChange}
        aria-label={`재생 속도 ${rate}x`}
        aria-expanded={open}
        className="flex h-8 items-center justify-center rounded-[8px] bg-neutral-h-50 px-[10px] py-[2px] text-[14px] font-semibold tracking-[-0.35px] text-neutral-h-800 transition-colors hover:bg-neutral-h-100 disabled:cursor-not-allowed disabled:opacity-30"
      >
        {rate}x
      </button>
      {open && (
        // Portalled so the popover escapes the timeline card's
        // overflow-hidden chrome. Anchored above the trigger via
        // AnchoredAbovePopover so it can still pop up out of the
        // editor's bottom toolbar.
        <AnchoredAbovePopover anchorRef={buttonRef} onClose={() => setOpen(false)}>
          <div className="flex flex-col items-center gap-[10px] rounded-[6px] bg-neutral-h-50 p-[6px] shadow-dialog">
            {PLAYBACK_OPTIONS.map((r) => {
              const selected = r === rate;
              return (
                <button
                  key={r}
                  type="button"
                  onClick={() => {
                    onChange?.(r);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex items-center justify-center rounded-[4px] px-1 text-[14px] font-semibold tracking-[-0.35px] text-neutral-h-800",
                    selected && "bg-neutral-h-200",
                  )}
                >
                  {r}x
                </button>
              );
            })}
          </div>
        </AnchoredAbovePopover>
      )}
    </>
  );
}

// Portal-based popover that anchors above the supplied trigger element.
// Lives here (vs in a shared primitive) because only TimelinePanel's
// speed + volume popovers need this exact "above the trigger" placement
// and they both share the same overflow-clip issue with the bottom
// editor card.
function AnchoredAbovePopover({
  anchorRef,
  onClose,
  children,
}: {
  anchorRef: React.RefObject<HTMLElement>;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: -9999, left: -9999 });
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Position the popover above the anchor, centred horizontally over it.
  // The actual width is content-driven, so we render to the DOM first,
  // measure, then recompute — handles both the speed list (auto width)
  // and the vertical volume slider (28px wide). Depending on ``mounted``
  // is critical: the position effect needs to fire AFTER createPortal
  // attaches the popover to the DOM, otherwise popoverRef.current is
  // null and the popover stays at (-9999, -9999) (the regression
  // surfaced 2026-05-18 as "volume/speed buttons do nothing").
  useEffect(() => {
    if (!mounted) return;
    const place = () => {
      const anchor = anchorRef.current;
      const popover = popoverRef.current;
      if (!anchor || !popover) return;
      const arect = anchor.getBoundingClientRect();
      const prect = popover.getBoundingClientRect();
      let top = arect.top - prect.height - 8;
      let left = arect.left + arect.width / 2 - prect.width / 2;
      const margin = 8;
      if (top < margin) top = margin;
      if (left < margin) left = margin;
      if (left + prect.width > window.innerWidth - margin) {
        left = window.innerWidth - prect.width - margin;
      }
      setPos({ top, left });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [anchorRef, mounted]);

  useEffect(() => {
    function handle(e: MouseEvent) {
      const target = e.target as Node;
      if (popoverRef.current && popoverRef.current.contains(target)) return;
      if (anchorRef.current && anchorRef.current.contains(target)) return;
      onClose();
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [anchorRef, onClose]);

  if (!mounted) return null;

  return createPortal(
    <div
      ref={popoverRef}
      style={{ position: "fixed", top: pos.top, left: pos.left, zIndex: 50 }}
    >
      {children}
    </div>,
    document.body,
  );
}

// figma export `2-5.a 쇼츠 편집(자막 선택)/상품 선택/lucide/play.svg` —
// solid filled triangle (no stroke). Replaces lucide-react's hollow
// Play so the transport cluster matches the figma spec exactly.
function PlayIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <path d="M4.16675 4.16716C4.16666 3.8739 4.24395 3.58582 4.39082 3.33199C4.53768 3.07816 4.74892 2.86757 5.00321 2.72149C5.25749 2.57541 5.54582 2.49901 5.83907 2.50001C6.13233 2.50101 6.42013 2.57936 6.67341 2.72716L16.6709 8.55883C16.9232 8.70523 17.1327 8.91528 17.2784 9.168C17.4241 9.42071 17.5009 9.70724 17.5011 9.99894C17.5014 10.2906 17.4251 10.5773 17.2798 10.8303C17.1346 11.0832 16.9255 11.2937 16.6734 11.4405L6.67341 17.2738C6.42013 17.4216 6.13233 17.5 5.83907 17.501C5.54582 17.502 5.25749 17.4256 5.00321 17.2795C4.74892 17.1334 4.53768 16.9228 4.39082 16.669C4.24395 16.4152 4.16666 16.1271 4.16675 15.8338V4.16716Z" />
    </svg>
  );
}

// figma export `... skip-back.svg` — left triangle + leading vertical
// bar. Fill + stroke share currentColor so the parent can recolor it
// (disabled state etc.) with the existing PILL_BUTTON text classes.
function SkipBackIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      stroke="currentColor"
      strokeWidth="1.66667"
      strokeLinecap="round"
      strokeLinejoin="round"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <path d="M2.5 16.6664V3.33302" fill="none" />
      <path d="M14.9758 3.57052C15.2287 3.41878 15.5174 3.33686 15.8123 3.33314C16.1072 3.32942 16.3978 3.40403 16.6545 3.54934C16.9112 3.69466 17.1247 3.90548 17.2732 4.16029C17.4217 4.41509 17.5 4.70475 17.5 4.99969V14.9997C17.5 15.2946 17.4217 15.5843 17.2732 15.8391C17.1247 16.0939 16.9112 16.3047 16.6545 16.45C16.3978 16.5954 16.1072 16.67 15.8123 16.6662C15.5174 16.6625 15.2287 16.5806 14.9758 16.4289L6.645 11.4305C6.39769 11.2828 6.19291 11.0734 6.05062 10.8229C5.90834 10.5724 5.83342 10.2893 5.83317 10.0012C5.83291 9.71314 5.90734 9.42991 6.04919 9.17916C6.19103 8.92842 6.39545 8.71872 6.6425 8.57052L14.9758 3.57052Z" />
    </svg>
  );
}

// figma export `... skip-forward.svg` — mirror of skip-back: right
// triangle + trailing vertical bar.
function SkipForwardIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      stroke="currentColor"
      strokeWidth="1.66667"
      strokeLinecap="round"
      strokeLinejoin="round"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <path d="M17.5 3.33302V16.6664" fill="none" />
      <path d="M5.02417 3.57052C4.77126 3.41878 4.48261 3.33686 4.18769 3.33314C3.89278 3.32942 3.60216 3.40403 3.3455 3.54934C3.08884 3.69466 2.87534 3.90548 2.7268 4.16029C2.57826 4.41509 2.5 4.70475 2.5 4.99969V14.9997C2.5 15.2946 2.57826 15.5843 2.7268 15.8391C2.87534 16.0939 3.08884 16.3047 3.3455 16.45C3.60216 16.5954 3.89278 16.67 4.18769 16.6662C4.48261 16.6625 4.77126 16.5806 5.02417 16.4289L13.355 11.4305C13.6023 11.2828 13.8071 11.0734 13.9494 10.8229C14.0917 10.5724 14.1666 10.2893 14.1668 10.0012C14.1671 9.71314 14.0927 9.42991 13.9508 9.17916C13.809 8.92842 13.6045 8.71872 13.3575 8.57052L5.02417 3.57052Z" />
    </svg>
  );
}

// figma: 1669:154040 — vertical slider popover, ~100×14 surface with -90deg
// rotated range input so drag-up = volume-up.
function VolumePopover({
  volume,
  onChange,
}: {
  volume: number;
  onChange?: (volume: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => onChange && setOpen((v) => !v)}
        disabled={!onChange}
        aria-label={`볼륨 ${Math.round(volume * 100)}%`}
        aria-expanded={open}
        className={PILL_BUTTON}
      >
        <Volume2 className="h-5 w-5" strokeWidth={1.5} />
      </button>
      {open && (
        // Portalled so the vertical slider doesn't get clipped by the
        // timeline card's overflow-hidden chrome; matches SpeedPopover's
        // anchoring approach.
        <AnchoredAbovePopover anchorRef={buttonRef} onClose={() => setOpen(false)}>
          <div className="flex h-[112px] w-[28px] items-center justify-center rounded-[4px] bg-neutral-h-50 px-[9px] py-[2px] shadow-dialog">
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={volume}
              onChange={(e) => onChange?.(Number(e.target.value))}
              aria-label={`볼륨 ${Math.round(volume * 100)}%`}
              className="h-[2px] w-[88px] -rotate-90 cursor-pointer accent-grayscale-800"
            />
          </div>
        </AnchoredAbovePopover>
      )}
    </>
  );
}


export function TimelinePanel({
  clips,
  subtitles,
  textOverlaysForTimeline,
  selectedTextOverlayId,
  onSelectTextOverlay,
  onUpdateTextOverlay,
  onReorderTextOverlay,
  onSplitAtPlayhead,
  onActivateRazor,
  razorMode = false,
  onRazorSplitClip,
  onRazorSplitSubtitle,
  zoom,
  playheadMs,
  playback,
  totalDurationMs,
  selectedClipIndex,
  selectedSubtitleIndex,
  onSelectClip,
  onSelectSubtitle,
  onTrimClip,
  onMoveClip,
  onReorderClips,
  onUpdateSubtitle,
  onAddSubtitle,
  onRemoveClip,
  onRemoveSubtitle,
  onTogglePlay,
  onSeek,
  onZoomChange,
  playbackRate = 1,
  onPlaybackRateChange,
  volume = 1.0,
  onVolumeChange,
  onToggleFullscreen,
  onPushHistory,
}: TimelinePanelProps) {
  const isPlaying = playback.kind === "playing";
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  // Live track of the scroll viewport's clientWidth. Passed to the
  // TimelineRuler so it can extend its timecode labels past the content
  // extent when the user zooms out far enough that the video occupies
  // only a small fraction of the visible width.
  const [containerWidth, setContainerWidth] = useState(0);
  // scrollLeft of the same container — needed by the ruler virtualizer
  // (L7) to filter marks down to the visible window. Tracked via a
  // throttled rAF wrapper inside onScroll so a fast drag doesn't fire
  // setState every frame.
  const [scrollLeft, setScrollLeft] = useState(0);
  const scrollLeftRafRef = useRef<number | null>(null);
  const handleScroll = useCallback(() => {
    if (scrollLeftRafRef.current != null) return;
    scrollLeftRafRef.current = requestAnimationFrame(() => {
      scrollLeftRafRef.current = null;
      const el = scrollContainerRef.current;
      if (el) setScrollLeft(el.scrollLeft);
    });
  }, []);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    setContainerWidth(el.clientWidth);
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setContainerWidth(entry.contentRect.width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Cancel any pending scroll rAF on unmount so we don't fire setState
  // on an unmounted component during a fast navigation.
  useEffect(() => {
    return () => {
      if (scrollLeftRafRef.current != null) {
        cancelAnimationFrame(scrollLeftRafRef.current);
      }
    };
  }, []);

  const SEEK_TOLERANCE_MS = 100;

  // Clip-boundary timestamps (sorted, deduped) for transport jump-to-prev/next.
  const boundaries = useMemo(() => {
    const set = new Set<number>([0, totalDurationMs]);
    for (const clip of clips) set.add(clip.timelineStartMs);
    return Array.from(set).sort((a, b) => a - b);
  }, [clips, totalDurationMs]);

  const handleSkipPrev = useCallback(() => {
    const target = [...boundaries].reverse().find((b) => b < playheadMs - SEEK_TOLERANCE_MS) ?? 0;
    onSeek(target);
  }, [boundaries, playheadMs, onSeek]);

  const handleSkipNext = useCallback(() => {
    const target = boundaries.find((b) => b > playheadMs + SEEK_TOLERANCE_MS) ?? totalDurationMs;
    onSeek(target);
  }, [boundaries, playheadMs, totalDurationMs, onSeek]);

  const hasSelection = selectedClipIndex != null || selectedSubtitleIndex != null;
  const handleDeleteSelection = useCallback(() => {
    if (selectedClipIndex != null) onRemoveClip(selectedClipIndex);
    else if (selectedSubtitleIndex != null) onRemoveSubtitle(selectedSubtitleIndex);
  }, [selectedClipIndex, selectedSubtitleIndex, onRemoveClip, onRemoveSubtitle]);

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

  // Subtitle track height is now locked to 48px regardless of zoom
  // (2026-05-18 review — operators expected the row's vertical extent
  // to stay constant while zoom only changed horizontal span). The
  // ``expanded`` prop on SubtitleTrack is no longer load-bearing.
  const isSubtitleExpanded = true;
  // Playhead height must match the actual rendered tracks area so the
  // cursor visually extends from the ruler down through every track
  // (text-overlay rows + subtitle + clip). Computed from the same
  // constants the strip uses so adding overlay rows automatically
  // grows the playhead too.
  // Row count = max(layerIndex) + 2 (one for the highest filled row
  // + one empty row above as drop-target), capped at 2 rows total
  // per operator policy 2026-05-24: '텍스트용 row는 최대 2개로 줄여줘'.
  const MAX_TEXT_OVERLAY_ROW_COUNT = 2;
  const maxOverlayLayer = (textOverlaysForTimeline ?? []).reduce(
    (acc, o) => Math.max(acc, o.layerIndex ?? 0),
    -1,
  );
  const textOverlayRowCount = Math.min(
    MAX_TEXT_OVERLAY_ROW_COUNT,
    maxOverlayLayer + 2,
  );
  const textOverlayStripHeight =
    textOverlayRowCount * 44 + Math.max(0, textOverlayRowCount - 1) * 2 + 4;
  const trackHeight = textOverlayStripHeight + 48 + 48;

  // Magnetic snap targets (T4) — built once per (subtitle/clip/overlay/
  // playhead/totalDuration) change and passed into draggable blocks.
  // Each block filters out its own edges via sourceId at drag time, so
  // we don't need to pre-filter the dragging element here.
  const snapPoints: SnapPoint[] = useMemo(
    () => [
      ...overlayEdgeSnapPoints(textOverlaysForTimeline ?? []),
      ...subtitleEdgeSnapPoints(subtitles),
      ...clipEdgeSnapPoints(clips),
      playheadSnapPoint(playheadMs),
      ...boundarySnapPoints(totalDurationMs),
    ],
    [
      textOverlaysForTimeline,
      subtitles,
      clips,
      playheadMs,
      totalDurationMs,
    ],
  );

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar — figma 1669:153949 (상단바) */}
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-grayscale-100 px-3">
        {/* LEFT cluster: trash icon + divider + playhead/total timecode */}
        <div className="flex w-[304px] shrink-0 items-center gap-3">
          <button
            type="button"
            onClick={handleDeleteSelection}
            disabled={!hasSelection}
            aria-label="선택 항목 삭제"
            className="rounded p-1 text-grayscale-700 transition-colors hover:bg-grayscale-100 hover:text-red-h-500 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <Trash2 className="h-5 w-5" strokeWidth={1.5} />
          </button>
          <div className="h-[26px] w-[2px] bg-grayscale-100" />
          <span className="text-[14px] font-semibold tracking-[-0.35px] text-grayscale-500">
            {formatVideoTimestampHMS(playheadMs)} / {formatVideoTimestampHMS(totalDurationMs)}
          </span>
        </div>

        {/* CENTER cluster: skip-back / play / skip-forward */}
        <div className="flex flex-1 items-center justify-center gap-[10px]">
          <button
            type="button"
            onClick={handleSkipPrev}
            disabled={playheadMs <= SEEK_TOLERANCE_MS}
            aria-label="이전 클립으로"
            className={PILL_BUTTON}
          >
            <SkipBackIcon className="h-5 w-5" />
          </button>
          <button
            type="button"
            onClick={onTogglePlay}
            disabled={clips.length === 0}
            aria-label={isPlaying ? "일시정지" : "재생"}
            className={PILL_BUTTON}
          >
            {isPlaying ? (
              <Pause className="h-5 w-5" strokeWidth={1.5} />
            ) : (
              <PlayIcon className="h-5 w-5" />
            )}
          </button>
          <button
            type="button"
            onClick={handleSkipNext}
            disabled={playheadMs >= totalDurationMs - SEEK_TOLERANCE_MS}
            aria-label="다음 클립으로"
            className={PILL_BUTTON}
          >
            <SkipForwardIcon className="h-5 w-5" />
          </button>
        </div>

        {/* RIGHT cluster: volume popover • speed popover • fullscreen */}
        <div className="flex items-center gap-[10px]">
          <VolumePopover volume={volume} onChange={onVolumeChange} />
          <SpeedPopover rate={playbackRate} onChange={onPlaybackRateChange} />
          {onToggleFullscreen && (
            <button
              type="button"
              onClick={onToggleFullscreen}
              aria-label="전체화면 미리보기"
              className={PILL_BUTTON}
            >
              <Maximize className="h-5 w-5" strokeWidth={1.5} />
            </button>
          )}
          {/* Split / razor (figma 2047:408589). Clicking enters razor
              mode; operator then clicks a clip or subtitle block to
              cut at that position. Active state shows navy-100 bg +
              ring so the operator knows the mode is on. */}
          {(onActivateRazor || onSplitAtPlayhead) && (
            <button
              type="button"
              onClick={onActivateRazor ?? onSplitAtPlayhead}
              aria-label="자르기 모드"
              aria-pressed={razorMode}
              className={cn(
                PILL_BUTTON,
                razorMode && "bg-heimdex-navy-100 ring-2 ring-heimdex-navy-500",
              )}
            >
              <SquareSplitHorizontal className="h-5 w-5" strokeWidth={1.5} />
            </button>
          )}
        </div>

        {/* FAR RIGHT: zoom slider (figma 1669:122130 — minus + 88px track + plus)
            Dynamic min so the 'fully zoomed out' state shows the whole
            clip in one screen — a 1 hr video lands at ~0.36 px/sec
            (1300 / 3600) instead of being stuck at the legacy 5 px/sec
            floor that left ~55 minutes off-screen. */}
        <div className="w-[156px] shrink-0">
          <TimelineZoomControl
            zoom={zoom}
            onZoomChange={onZoomChange}
            minZoom={Math.max(0.1, 1300 / Math.max(1, totalDurationMs / 1000))}
          />
        </div>
      </div>

      {/* Scrollable timeline area — both axes scroll. Horizontal for
          zoom-out content past the viewport; vertical so additional
          operator text-overlay rows stack within the fixed wrapper
          height (2026-05-22 spec). scrollbar-hidden keeps the chrome
          clean — operators rely on dragging instead.
          onScroll feeds the ruler virtualizer (L7) so labels off-
          screen don't pay DOM cost. */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        // 2026-05-22 figma 2047:408670 — wrapper-internal split:
        //   * outer scroll = horizontal only (zoom past viewport width).
        //   * track-area vertical scroll lives on the inner container
        //     so the ruler stays pinned above when text-overlay rows
        //     stack past 189 px.
        className="scrollbar-hidden flex-1 overflow-x-auto overflow-y-hidden"
      >
        {/* 12px left inset so the "0s" label and the first clip don't
            sit flush against the wrapper's left edge — matches the
            2026-05-18 spec ("타임라인 0S는 wrapper 좌측끝으로부터 12PX 띄움").
            Padding lives on the inner container so ruler / clips /
            subtitles / playhead all shift together and stay aligned. */}
        <div className="relative pl-[12px]" style={{ minWidth: "100%" }}>
          {/* Ruler — clicking anywhere on the ruler seeks the playhead
              to that timecode. Reuses the same onSeek the playhead drag
              already calls, so audio + preview sync paths converge on
              one path. */}
          <TimelineRuler
            totalDurationMs={totalDurationMs}
            zoom={zoom}
            onSeek={onSeek}
            minWidthPx={containerWidth}
            viewportLeftPx={scrollLeft}
            viewportRightPx={scrollLeft + containerWidth}
          />

          {/* Tracks area — figma 2045:330070 caps this at 152 px
              (44 subtitle + 4 gap + 108 clip-with-thumbnails) so the
              wrapper height matches the 252-px reference frame at
              1440 viewport. Surplus rows (operator-added overlays)
              scroll vertically inside this container; the outer
              wrapper height + the page's pb-[20px] therefore stay
              constant on every viewport. */}
          <div className="scrollbar-hidden h-[152px] overflow-y-auto">
          {/* Operator text-overlay strip — always renders at least
              MIN_TEXT_OVERLAY_ROWS slots so the operator sees explicit
              drop targets above the (host) subtitle row. Empty rows
              appear ABOVE existing overlay rows so overlays stack from
              the bottom (closest to the subtitle row), matching the
              operator's mental model 'from bottom: video, subtitle,
              text-overlay rows'. */}
          {(() => {
            // Row position = overlay.layerIndex (0 = bottom, closest
            // to subtitle row; higher = visually above). Always show
            // one empty row above the highest filled row so the
            // operator sees where the next 텍스트 추가 will land —
            // BUT cap the total at MAX_TEXT_OVERLAY_ROWS so drag can
            // never spawn a 3rd row (matches the reducer cap on
            // REORDER_OVERLAY layerIndex; operator policy 2026-05-24).
            const MAX_TEXT_OVERLAY_ROWS = 2;
            const list = textOverlaysForTimeline ?? [];
            const maxFilledLayer = list.reduce(
              (acc, o) => Math.max(acc, o.layerIndex ?? 0),
              -1,
            );
            const topRow = Math.min(
              MAX_TEXT_OVERLAY_ROWS - 1,
              maxFilledLayer + 1,
            );
            const overlaysByRow = new Map<number, typeof list>();
            for (const o of list) {
              const row = (o as { layerIndex?: number }).layerIndex ?? 0;
              const arr = overlaysByRow.get(row) ?? [];
              arr.push(o);
              overlaysByRow.set(row, arr);
            }
            const rows: number[] = [];
            for (let r = topRow; r >= 0; r--) rows.push(r);
            return (
              <div
                className="mb-1 flex flex-col gap-0.5"
                style={{ width: `${Math.max(containerWidth, msToPixels(totalDurationMs, zoom))}px` }}
              >
                {rows.map((row) => {
                  const overlaysHere = overlaysByRow.get(row) ?? [];
                  return (
                    <div
                      key={`overlay-row-${row}`}
                      className="relative h-[44px] shrink-0 overflow-hidden rounded-l-[10px] bg-grayscale-100"
                    >
                      {overlaysHere.map((sub) => (
                        <TextOverlayBlock
                          key={sub.id}
                          overlayId={sub.id}
                          text={sub.text}
                          startMs={sub.startMs}
                          endMs={sub.endMs}
                          zoom={zoom}
                          isSelected={selectedTextOverlayId === sub.id}
                          onSelect={() => onSelectTextOverlay?.(sub.id)}
                          onUpdate={(id, updates) =>
                            onUpdateTextOverlay?.(id, updates)
                          }
                          onSeek={onSeek}
                          onPushHistory={onPushHistory}
                          snapPoints={snapPoints}
                          onReorder={onReorderTextOverlay}
                        />
                      ))}
                    </div>
                  );
                })}
              </div>
            );
          })()}

          {/* Subtitle track — figma 1669:49003: subtitles row sits ABOVE clips */}
          <SubtitleTrack
            subtitles={subtitles}
            zoom={zoom}
            totalDurationMs={totalDurationMs}
            playheadMs={playheadMs}
            selectedSubtitleIndex={selectedSubtitleIndex}
            onSelectSubtitle={onSelectSubtitle}
            onUpdateSubtitle={onUpdateSubtitle}
            onAddSubtitle={onAddSubtitle}
            onSeek={onSeek}
            onPushHistory={onPushHistory}
            expanded={isSubtitleExpanded}
            snapPoints={snapPoints}
            razorMode={razorMode}
            onRazorSplitSubtitle={onRazorSplitSubtitle}
          />

          {/* Clip track — figma 1669:49030: scene row below the subtitle row */}
          <ClipTrack
            clips={clips}
            subtitles={subtitles}
            zoom={zoom}
            selectedClipIndex={selectedClipIndex}
            totalDurationMs={totalDurationMs}
            playheadMs={playheadMs}
            onSelectClip={onSelectClip}
            onTrimClip={onTrimClip}
            onMoveClip={onMoveClip}
            onSeek={onSeek}
            razorMode={razorMode}
            onRazorSplitClip={onRazorSplitClip}
          />
          </div>

          {/* Playhead cursor — wrapped in a 12-px-shifted positioned
              container so its coordinate origin matches the subtitle
              / clip / overlay blocks. Those blocks live inside
              SubtitleTrack / ClipTrack which sit at the wrapper's
              CONTENT edge (= outer wrapper left + 12 px padding).
              PlayheadCursor is absolutely positioned, so its left is
              measured from the containing block's PADDING edge —
              without this wrapper that was the outer wrapper's left,
              i.e. 12 px behind where a SubtitleBlock at the same ms
              actually renders. Result: playhead sat 12 px ahead of
              the subtitle box's visible start. Wrapping moves the
              containing block to the content edge so left=msToPixels
              now lines up with SubtitleBlock left=msToPixels at the
              same ms (Task #18). */}
          <div className="pointer-events-none absolute inset-y-0 left-[12px] right-0">
            <PlayheadCursor
              playheadMs={playheadMs}
              zoom={zoom}
              height={trackHeight}
              onSeek={onSeek}
              showTooltip
            />
          </div>
        </div>
      </div>
    </div>
  );
}
