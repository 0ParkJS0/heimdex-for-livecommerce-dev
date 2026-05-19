"use client";

import { useRef, useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import type { EditorClip, EditorSubtitle, HistoryEntry } from "../lib/types";
import type { EditorOverlay } from "../lib/overlay-types";
import { OverlayRenderer } from "./preview/OverlayRenderer";
import { SubtitleCancelActionBar } from "./SubtitleCancelActionBar";
import { getActiveSubtitles } from "../lib/source-time";
import { formatTimelineTimestamp } from "../lib/timeline-math";
import { resolveFontFamily } from "@/lib/fonts";
import { usePlaybackSync } from "../hooks/usePlaybackSync";
import { getThumbnailAspectClass, type ThumbnailAspectRatio } from "@/lib/thumbnailUtils";

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
  isPlaying: boolean;
  totalDurationMs: number;
  selectedSubtitleIndex: number | null;
  onPlayheadChange: (ms: number) => void;
  onPlayingChange: (playing: boolean) => void;
  onSelectSubtitle: (index: number | null) => void;
  onUpdateSubtitlePosition: (index: number, positionX: number, positionY: number) => void;
  onUpdateSubtitleFontSize: (index: number, fontSizePx: number) => void;
  // Undo plumbing — preview captures a pre-gesture snapshot on each
  // drag/resize/rotate pointerdown so Ctrl+Z can roll one step back.
  // Optional so existing callers (e.g. embedded preview tiles that
  // don't surface dragging) don't break.
  onPushHistory?: (entry: HistoryEntry) => void;
  // when true, the preview container expands to the 352×626 iPhone
  // mockup size used inside FullscreenOverlay. Layout/logic otherwise identical.
  fullscreen?: boolean;
  // playback rate forwarded to <video>. Optional (1.0 default).
  playbackRate?: number;
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
  isPlaying,
  totalDurationMs,
  selectedSubtitleIndex,
  onPlayheadChange,
  onPlayingChange,
  onSelectSubtitle,
  onUpdateSubtitlePosition,
  onUpdateSubtitleFontSize,
  onPushHistory,
  fullscreen = false,
  playbackRate,
}: PreviewPanelProps) {
  const {
    videoRef,
    preloadRef,
    togglePlay,
    onSeeked,
    onEnded,
  } = usePlaybackSync({
    clips,
    playheadMs,
    isPlaying,
    onPlayheadChange,
    onPlayingChange,
    rate: playbackRate,
  });

  // The shorts editor canvas is always 9:16 (vertical reels/shorts output);
  // the org-wide thumbnail_aspect_ratio setting governs other surfaces.
  const aspectRatio: ThumbnailAspectRatio = "9:16";

  const activeSubtitles = getActiveSubtitles(subtitles, playheadMs);
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

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();

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
        onUpdateOverlay(ovDrag.overlayId, {
          transform: {
            ...overlay.transform,
            rotationDeg: clamped,
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
  }, [onUpdateSubtitlePosition, onUpdateSubtitleFontSize, onUpdateOverlay, overlays]);

  const handlePointerUp = useCallback(() => {
    dragRef.current = null;
    overlayDragRef.current = null;
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
      className="relative h-full w-full"
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
    >
      {/* Preview container — figma 1602:37722: shorts canvas fills the card
          surface so the editor center is the 9:16 stage with no padding. */}
      <div
        ref={containerRef}
        className={cn(
          "relative overflow-hidden bg-black",
          aspectRatio === "9:16"
            ? "h-full w-full"
            : fullscreen
              ? "aspect-video w-full max-w-[626px] rounded-[10px]"
              : "aspect-video w-full max-w-[480px] rounded-[10px]",
        )}
        onClick={() => onSelectSubtitle(null)}
      >
        {/* Main video element */}
        <video
          ref={videoRef}
          className="h-full w-full object-contain"
          playsInline
          onSeeked={onSeeked}
          onEnded={onEnded}
        />

        {/* Subtitle overlay */}
        {activeSubtitles.map((sub) => {
          const idx = getSubtitleIndex(sub.id);
          const isSelected = idx >= 0 && idx === selectedSubtitleIndex;
          const isDraggingThis = dragRef.current?.subtitleIndex === idx && dragRef.current?.mode === "move";

          return (
            <div
              key={sub.id}
              data-subtitle-box
              className={cn(
                "absolute",
                isSelected ? "cursor-grab z-10" : "cursor-grab",
              )}
              style={{
                left: `${sub.style.positionX * 100}%`,
                top: `${sub.style.positionY * 100}%`,
                transform: "translate(-50%, -50%)",
                pointerEvents: "auto",
                // 2026-05-19 — see OverlayRenderer for the rationale on
                // `width: max-content`. The lockedWidth branch below
                // still wins during an active drag because it lands
                // later in the spread.
                width: "max-content",
                ...(isDraggingThis && dragRef.current?.lockedWidth
                  ? { width: `${dragRef.current.lockedWidth}px` }
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
                    // 2026-05-19 — bumped from 0.5 → 0.55 so the inline
                    // preview matches the fullscreen modal's subtitle
                    // scale (FullscreenOverlay.tsx uses 0.55). Both
                    // surfaces render the same composition; their on-
                    // screen pill sizes should agree relative to the
                    // host canvas. Fullscreen is the reference (it
                    // mirrors the figma 9:16 phone frame); the inline
                    // preview now follows.
                    fontSize: `${Math.max(8, sub.style.fontSizePx * 0.55)}px`,
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
        })}

        {/* V2 overlays — rendered above subtitles. The active-window check
            mirrors getActiveSubtitles: only show overlays whose [start, end)
            includes the current playhead. */}
        {overlays
          .filter((o) => o.startMs <= playheadMs && playheadMs < o.endMs)
          .map((o) => (
            <OverlayRenderer
              key={o.id}
              overlay={o}
              isSelected={selectedOverlayId === o.id}
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
            />
          ))}

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
