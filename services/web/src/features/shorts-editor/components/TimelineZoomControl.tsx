"use client";

// figma: 1670:185907 — 타임라인 zoom 슬라이더 (minus icon + 88px track + plus icon)
//        1669:154010 (펼침) / 1669:49002 (접힘) — zoom 변동 시 자막 섹션 펼침/접힘 신호로도 사용
//
// 2026-05-22 — accepts an optional minZoom prop. The caller computes
// minZoom from the video duration + timeline viewport width so the
// 'max zoom out' state shows the entire clip in one screen (Figma
// spec: 1 hr video → full hour visible at min zoom). When omitted,
// falls back to the constants module default.
import { useCallback } from "react";
import { MIN_ZOOM, MAX_ZOOM } from "../constants";

interface TimelineZoomControlProps {
  zoom: number;
  onZoomChange: (zoom: number) => void;
  minZoom?: number;
}

const STEP = 25;

function MinusIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M18 12H6" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m6-6H6" />
    </svg>
  );
}

export function TimelineZoomControl({
  zoom,
  onZoomChange,
  minZoom,
}: TimelineZoomControlProps) {
  // Floor the dynamic min at 0.1 px/sec so a freshly-loaded session
  // with totalDurationMs === 0 doesn't end up dividing by zero.
  const effectiveMin = Math.max(0.1, minZoom ?? MIN_ZOOM);
  const handleDec = useCallback(() => {
    onZoomChange(Math.max(effectiveMin, zoom - STEP));
  }, [zoom, onZoomChange, effectiveMin]);

  const handleInc = useCallback(() => {
    onZoomChange(Math.min(MAX_ZOOM, zoom + STEP));
  }, [zoom, onZoomChange]);

  // Tiny epsilon so the disabled check survives float rounding from
  // the slider drag (otherwise a value of 0.367000001 stays enabled
  // even though the user is effectively at min).
  const EPS = 0.01;

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={handleDec}
        disabled={zoom <= effectiveMin + EPS}
        aria-label="타임라인 축소"
        className="rounded p-0.5 text-grayscale-700 hover:bg-grayscale-100 disabled:cursor-not-allowed disabled:opacity-30"
      >
        <MinusIcon />
      </button>
      <input
        type="range"
        min={effectiveMin}
        max={MAX_ZOOM}
        step="any"
        value={zoom}
        onChange={(e) => onZoomChange(Number(e.target.value))}
        aria-label={`타임라인 배율 ${zoom}%`}
        className="h-[2px] w-[88px] cursor-pointer accent-grayscale-800"
      />
      <button
        type="button"
        onClick={handleInc}
        disabled={zoom >= MAX_ZOOM - EPS}
        aria-label="타임라인 확대"
        className="rounded p-0.5 text-grayscale-700 hover:bg-grayscale-100 disabled:cursor-not-allowed disabled:opacity-30"
      >
        <PlusIcon />
      </button>
    </div>
  );
}
