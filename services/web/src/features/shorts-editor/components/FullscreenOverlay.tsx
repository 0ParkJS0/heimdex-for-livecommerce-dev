"use client";

// figma: 1682:187740 — 전체보기 모달
// spec: backdrop bg-[rgba(2,3,20,0.4)] backdrop-blur, centered card bg-white r-20 p-20 gap-10
//       header row: filename 16px semibold + [닫기] secondary
//       phone frame 387×688 r-10 with overlays
//       bottom player row: progress (white track / heimdex-navy fill) + play/skip pills

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { cn } from "@/lib/utils";
import type { EditorClip, EditorSubtitle, EditorState, LayerOrderId, Playback, PlaybackEvent } from "../lib/types";
import type { EditorOverlay } from "../lib/overlay-types";
import { OverlayRenderer } from "./preview/OverlayRenderer";
import { getActiveSubtitles, getVisibleSubtitles } from "../lib/source-time";
import { formatTimelineTimestamp } from "../lib/timeline-math";
import { resolveFontFamily } from "@/lib/fonts";
import { usePlaybackSync } from "../hooks/usePlaybackSync";

interface FullscreenOverlayProps {
  clips: EditorClip[];
  subtitles: EditorSubtitle[];
  overlays?: EditorOverlay[];
  selectedOverlayId?: string | null;
  onSelectOverlay?: (id: string | null) => void;
  onUpdateOverlay?: (id: string, updates: Partial<EditorOverlay>) => void;
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
  onClose: () => void;
  filename?: string;
  // Global letterbox bars (figma 1682:187740 + Q4 윤곽선). Rendered
  // read-only here so the fullscreen preview mirrors what PreviewPanel
  // shows; bar heights are only editable through the inline canvas.
  letterbox?: EditorState["letterbox"];
  // Unified stack order. When provided, letterbox + subtitles +
  // overlays pick their zIndex from this array so the fullscreen
  // surface matches the live preview's z-order.
  layerOrder?: LayerOrderId[];
  // 2026-05-24 — mirror the operator-added video transform here so
  // the fullscreen modal stays visually faithful to the editor canvas
  // (and to the final composition the worker will render). All fields
  // are optional — omitting them collapses to the default centred
  // 1× / 0° / no-outline / no-shadow presentation.
  videoTransform?: EditorState["videoTransform"];
}

export function FullscreenOverlay({
  clips,
  subtitles,
  overlays = [],
  selectedOverlayId = null,
  onSelectOverlay,
  playheadMs,
  playback,
  totalDurationMs,
  onPlayheadChange,
  dispatchPlaybackEvent,
  onClose,
  filename,
  letterbox,
  layerOrder,
  videoTransform,
}: FullscreenOverlayProps) {
  const isPlaying = playback.kind === "playing";
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      // Arrow-key seek inside the fullscreen modal. Shift narrows the
      // step to 1s for finer scrubbing; plain arrows match the on-screen
      // SkipBack/SkipForward buttons (±5s). Ignored while the user is
      // typing in a form control (lets dialogs/inputs keep their native
      // caret-move semantics).
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) {
        return;
      }
      if (e.key === "ArrowLeft") {
        const step = e.shiftKey ? 1000 : 5000;
        onPlayheadChange(Math.max(0, playheadMs - step));
      } else if (e.key === "ArrowRight") {
        const step = e.shiftKey ? 1000 : 5000;
        onPlayheadChange(Math.min(totalDurationMs, playheadMs + step));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onPlayheadChange, playheadMs, totalDurationMs]);

  const { videoRef, preloadRef, togglePlay, onSeeked, onEnded } = usePlaybackSync({
    clips,
    playheadMs,
    playback,
    onPlayheadChange,
    dispatchPlaybackEvent,
  });

  const visibleSubtitles = getVisibleSubtitles(subtitles, clips);
  const activeSubtitles = getActiveSubtitles(visibleSubtitles, playheadMs);
  const progressPct =
    totalDurationMs > 0 ? Math.min(100, (playheadMs / totalDurationMs) * 100) : 0;

  const handleSkipBack = () => onPlayheadChange(Math.max(0, playheadMs - 5000));
  const handleSkipForward = () =>
    onPlayheadChange(Math.min(totalDurationMs, playheadMs + 5000));

  // Portal to document.body so the modal escapes any parent stacking
  // context (selected overlays in PreviewPanel use inline zIndex which
  // could poke through a non-portalled modal).
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null);
  useEffect(() => {
    setPortalTarget(document.body);
  }, []);

  const content = (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="쇼츠 미리보기 전체보기"
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-[rgba(2,3,20,0.4)] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex flex-col items-start gap-[10px] rounded-[20px] bg-white p-5 shadow-[2px_2px_20px_0px_rgba(0,0,0,0.25)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header row — filename + close */}
        <div className="flex w-full items-start justify-between">
          <p className="text-[16px] font-semibold leading-[1.4] tracking-[-0.4px] text-black">
            {filename ?? "쇼츠 미리보기"}
          </p>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 items-center rounded-[8px] border border-neutral-h-500 bg-white px-[10px] py-[6px] text-[12px] font-semibold text-neutral-h-500 transition-colors hover:bg-grayscale-10"
          >
            닫기
          </button>
        </div>

        {/* Vertical phone frame — figma 387×688. ``containerType: size``
            opts this canvas into CSS container queries so overlay font
            sizes inside the frame scale with its actual dimensions
            (same pattern as PreviewPanel). */}
        <div
          className="relative flex h-[688px] w-[387px] items-end justify-center overflow-hidden rounded-[10px] bg-black"
          style={{ containerType: "size" }}
          onClick={() => onSelectOverlay?.(null)}
        >
          {/* Host video — wrapped so we can apply ``filter:drop-shadow``
              on the wrapper (which includes the CSS outline) while
              keeping the <video> element clean for transform/outline.
              ``object-contain`` matches PreviewPanel so scale+position
              math lines up exactly between the two surfaces. */}
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
            const dropShadowCss = vShadow
              ? (() => {
                  const layers: string[] = [];
                  const spread = Math.max(0, vShadow.spreadPx);
                  const layerCount =
                    spread > 0 ? Math.min(8, 1 + Math.floor(spread / 4)) : 1;
                  for (let i = 0; i < layerCount; i += 1) {
                    layers.push(
                      `drop-shadow(${vShadow.offsetX}px ${vShadow.offsetY}px ${vShadow.blurPx}px ${vShadow.color})`,
                    );
                  }
                  return layers.join(" ");
                })()
              : undefined;
            return (
              <div
                className="absolute inset-0"
                style={{
                  ...(videoZIndex != null && videoZIndex >= 0
                    ? { zIndex: videoZIndex }
                    : {}),
                  ...(dropShadowCss ? { filter: dropShadowCss } : {}),
                }}
              >
                <video
                  ref={videoRef}
                  className="h-full w-full object-contain"
                  style={{
                    transform: `scale(${vs}) translate(${(vx - 0.5) * 100}%, ${(vy - 0.5) * 100}%) rotate(${vRot}deg)`,
                    ...(vOutline && vOutline.widthPx > 0
                      ? {
                          outline: `${vOutline.widthPx}px solid ${vOutline.color}`,
                        }
                      : {}),
                  }}
                  playsInline
                  onSeeked={onSeeked}
                  onEnded={onEnded}
                />
              </div>
            );
          })()}
          <video ref={preloadRef} className="hidden" preload="auto" muted playsInline />

          {/* Subtitles — center-aligned figma style.
              DOM structure mirrors PreviewPanel exactly: an outer
              absolute <div> with width:max-content + maxWidth:85%
              wraps the <p>. This ensures the shrink-to-fit + keep-all
              wrapping produces identical line breaks on both surfaces
              (Bug 1 — subtitle wrap parity).
              zIndex derived from layerOrder so subtitles render above
              the letterbox bars (Bug 7). */}
          {(() => {
            const subtitleZIndex = layerOrder
              ? layerOrder.findIndex((l) => l.kind === "subtitles")
              : 10;
            const subZ = subtitleZIndex >= 0 ? subtitleZIndex : 10;
            return activeSubtitles.map((sub) => (
            <div
              key={sub.id}
              className="pointer-events-none absolute"
              style={{
                left: `${sub.style.positionX * 100}%`,
                top: `${sub.style.positionY * 100}%`,
                transform: "translate(-50%, -50%)",
                width: "max-content",
                maxWidth: "85%",
                zIndex: subZ,
              }}
            >
              <p
                className="whitespace-pre-wrap select-none text-center"
                style={{
                  fontFamily: resolveFontFamily(sub.style.fontFamily),
                  // 2026-05-20 — container-query scale matching PreviewPanel
                  // and OverlayRenderer. ``fontSizePx`` is stored in 720-
                  // tall output coords; ``100cqh / 720`` resolves to the
                  // current phone-frame fraction (688/720 ≈ 0.955 here).
                  fontSize: `max(8px, calc(${sub.style.fontSizePx} * 100cqh / 720))`,
                  color: sub.style.fontColor,
                  fontWeight: sub.style.fontWeight,
                  textAlign: "center",
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
            </div>
          ));
          })()}

          {/* V2 overlays — full styling via OverlayRenderer */}
          {overlays
            .filter((o) => o.startMs <= playheadMs && playheadMs < o.endMs)
            .map((o) => {
              const overlayZIndex = layerOrder
                ? layerOrder.findIndex(
                    (l) => l.kind === "overlay" && l.id === o.id,
                  )
                : undefined;
              return (
                <OverlayRenderer
                  key={o.id}
                  overlay={o}
                  isSelected={selectedOverlayId === o.id}
                  zIndex={
                    overlayZIndex != null && overlayZIndex >= 0
                      ? overlayZIndex
                      : undefined
                  }
                  onClick={() => onSelectOverlay?.(o.id)}
                />
              );
            })}

          {/* Global letterbox bars — mirror PreviewPanel rendering so
              the fullscreen modal shows the same letterbox the operator
              configured. Read-only here (no drag handles). zIndex from
              layerOrder when available; falls back to 15 to sit above
              the host video and below subtitles. */}
          {letterbox &&
            (() => {
              const lbZIndex = layerOrder
                ? layerOrder.findIndex((l) => l.kind === "letterbox")
                : 15;
              const lbZ = lbZIndex >= 0 ? lbZIndex : 15;
              return (
                <>
                  {letterbox.topHeightPct > 0 && (
                    <div
                      className="pointer-events-none absolute left-0 right-0 top-0"
                      style={{
                        height: `${letterbox.topHeightPct}%`,
                        backgroundColor: letterbox.fillColor,
                        zIndex: lbZ,
                        borderBottom:
                          letterbox.borderColor && letterbox.borderWidthPx > 0
                            ? `${letterbox.borderWidthPx}px solid ${letterbox.borderColor}`
                            : undefined,
                      }}
                    />
                  )}
                  {letterbox.bottomHeightPct > 0 && (
                    <div
                      className="pointer-events-none absolute bottom-0 left-0 right-0"
                      style={{
                        height: `${letterbox.bottomHeightPct}%`,
                        backgroundColor: letterbox.fillColor,
                        zIndex: lbZ,
                        borderTop:
                          letterbox.borderColor && letterbox.borderWidthPx > 0
                            ? `${letterbox.borderWidthPx}px solid ${letterbox.borderColor}`
                            : undefined,
                      }}
                    />
                  )}
                </>
              );
            })()}

          {/* Bottom transport row — figma 1682:187750 */}
          <div className="relative z-10 flex w-full flex-col gap-3 p-[10px]">
            {/* Click anywhere on the bar to seek the playhead to that
                runtime. Mirrors the timeline-ruler click-to-seek the
                editor body already exposes, so the fullscreen surface
                doesn't lose that affordance. */}
            <div
              className="relative h-1 w-full cursor-pointer bg-white"
              role="slider"
              aria-label="재생 위치 이동"
              aria-valuemin={0}
              aria-valuemax={totalDurationMs}
              aria-valuenow={playheadMs}
              onClick={(e) => {
                if (totalDurationMs <= 0) return;
                const rect = e.currentTarget.getBoundingClientRect();
                const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
                onPlayheadChange(Math.round(ratio * totalDurationMs));
              }}
            >
              <div
                className="pointer-events-none h-full bg-heimdex-navy-500 transition-[width]"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <div className="flex items-center gap-[10px]">
              <button
                type="button"
                onClick={togglePlay}
                aria-label={isPlaying ? "일시정지" : "재생"}
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full text-white",
                  "bg-[rgba(38,38,38,0.5)] hover:bg-[rgba(38,38,38,0.7)]",
                )}
              >
                {isPlaying ? (
                  <Pause className="h-5 w-5" />
                ) : (
                  <Play className="h-5 w-5" />
                )}
              </button>
              <div className="flex h-8 items-center justify-between gap-2 rounded-full bg-[rgba(38,38,38,0.5)] px-2">
                <button
                  type="button"
                  onClick={handleSkipBack}
                  aria-label="5초 뒤로"
                  className="text-white hover:text-white/80"
                >
                  <SkipBack className="h-5 w-5" />
                </button>
                <button
                  type="button"
                  onClick={handleSkipForward}
                  aria-label="5초 앞으로"
                  className="text-white hover:text-white/80"
                >
                  <SkipForward className="h-5 w-5" />
                </button>
              </div>
              <div className="flex h-8 items-center rounded-full bg-[rgba(38,38,38,0.5)] px-2">
                <span className="text-[14px] font-medium leading-[1.4] tracking-[-0.35px] text-white">
                  {formatTimelineTimestamp(playheadMs)} /{" "}
                  {formatTimelineTimestamp(totalDurationMs)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return portalTarget ? createPortal(content, portalTarget) : content;
}
