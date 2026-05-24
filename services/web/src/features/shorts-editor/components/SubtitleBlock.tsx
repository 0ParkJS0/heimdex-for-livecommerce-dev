"use client";

// figma: 1713:271669  (cache: .figma-cache/1713-271669_phase5_editor-1.api.json)
// node-name: Subtitle Block · spec: Block 자막 미리보기 fs=10 fw=500 → text-[10px] font-medium
import { useCallback, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { EditorSubtitle, HistoryEntry } from "../lib/types";
import { msToPixels, pixelsToMs } from "../lib/timeline-math";
import { getSnapThresholdMs, resolveSnap, type SnapPoint } from "../lib/snap";

interface SubtitleBlockProps {
  subtitle: EditorSubtitle;
  index: number;
  zoom: number;
  isSelected: boolean;
  onSelect: () => void;
  onUpdate: (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => void;
  // Click-snap: when the user clicks a subtitle block we move the
  // playhead to its start so the preview jumps to the matching frame
  // (2026-05-18 review — the playhead was previously lagging behind).
  onSeek?: (ms: number) => void;
  // Undo plumbing — pushed on pointerdown so Ctrl+Z can roll back the
  // time-drag (start/end/move) gesture in one stroke. Optional so
  // callers that don't surface dragging (read-only embeds) skip it.
  onPushHistory?: (entry: HistoryEntry) => void;
  // Magnetic snap targets (T4). Block filters its own edges out at
  // drag time via sourceId === subtitle.id. Optional so read-only
  // embeds can skip snapping.
  snapPoints?: SnapPoint[];
  razorMode?: boolean;
  onRazorSplit?: (atMs: number) => void;
}

const FRAME_MS = 1000 / 30;

export function SubtitleBlock({
  subtitle,
  index,
  zoom,
  isSelected,
  onSelect,
  onUpdate,
  onSeek,
  onPushHistory,
  snapPoints,
  razorMode = false,
  onRazorSplit,
}: SubtitleBlockProps) {
  const leftPx = msToPixels(subtitle.startMs, zoom);
  // Subtract a 2px gutter from the rendered width so back-to-back
  // subtitle blocks at minimum zoom show a 2px gap between them — the
  // 2026-05-18 review surfaced that adjacent blocks were merging into a
  // single solid bar when the timeline was compressed. The minimum
  // visual width is still 8px so very short subtitles stay clickable.
  const rawWidthPx = msToPixels(subtitle.endMs - subtitle.startMs, zoom);
  const widthPx = Math.max(rawWidthPx - 2, 8);

  // ---------------------------------------------------------------------------
  // Drag / resize implementation.
  //
  // 2026-05-19 — the previous useCallback-based listener wiring suffered
  // a churn bug: every drag move called ``onUpdate`` which re-rendered
  // the parent, which produced a new ``onUpdate`` function identity
  // each render. That changed ``onPointerMove``'s useCallback identity,
  // which changed the useEffect cleanup's deps, which fired cleanup
  // synchronously and ripped the pointermove listener off the document.
  // The user saw the block move ~1px (the first event after pointerdown)
  // and then freeze.
  //
  // The fix is the "useEvent" pattern: stash the latest ``onUpdate``
  // and ``zoom`` in refs that we read inside the document-level handler.
  // The handler itself is created once per drag session inside
  // ``handlePointerDown`` and torn down only at pointerup — so listener
  // identity is stable for the duration of the drag and listener churn
  // can't kill mid-drag tracking.
  // ---------------------------------------------------------------------------
  const draggingRef = useRef<"move" | "start" | "end" | null>(null);
  const startXRef = useRef(0);
  const startValuesRef = useRef({ startMs: 0, endMs: 0 });

  // Latest callback/zoom/snap mirrored into refs so the document-level
  // handler always reads fresh values without subscribing to them.
  const onUpdateRef = useRef(onUpdate);
  const zoomRef = useRef(zoom);
  const indexRef = useRef(index);
  const snapPointsRef = useRef(snapPoints);
  const idRef = useRef(subtitle.id);
  useEffect(() => {
    onUpdateRef.current = onUpdate;
    zoomRef.current = zoom;
    indexRef.current = index;
    snapPointsRef.current = snapPoints;
    idRef.current = subtitle.id;
  });

  const handlePointerDown = useCallback(
    (mode: "move" | "start" | "end") => (e: React.PointerEvent) => {
      e.stopPropagation();
      // Snapshot the pre-gesture window so Ctrl+Z can roll back the
      // entire move / start-edge / end-edge drag in one stroke. Pushed
      // on pointerdown so the first pointermove already has an entry
      // to undo to.
      onPushHistory?.({
        kind: "subtitle_time",
        index,
        startMs: subtitle.startMs,
        endMs: subtitle.endMs,
      });
      draggingRef.current = mode;
      startXRef.current = e.clientX;
      startValuesRef.current = {
        startMs: subtitle.startMs,
        endMs: subtitle.endMs,
      };

      const handleMove = (ev: PointerEvent) => {
        if (!draggingRef.current) return;
        const dx = ev.clientX - startXRef.current;
        const z = zoomRef.current;
        const deltaMs = pixelsToMs(dx, z);
        const { startMs, endMs } = startValuesRef.current;
        const i = indexRef.current;
        const update = onUpdateRef.current;
        // Filter our own edges out of the snap candidates so a subtitle
        // can't snap to itself. Same pattern as TextOverlayBlock.
        const candidates = (snapPointsRef.current ?? []).filter(
          (p) => p.sourceId !== idRef.current,
        );
        const thresholdMs = getSnapThresholdMs(z);

        if (draggingRef.current === "move") {
          const rawStart = Math.max(0, Math.round(startMs + deltaMs));
          const duration = endMs - startMs;
          const snapped = resolveSnap(rawStart, candidates, thresholdMs);
          const newStart = snapped?.ms ?? rawStart;
          update(i, { startMs: newStart, endMs: newStart + duration });
        } else if (draggingRef.current === "start") {
          const rawStart = Math.max(0, Math.round(startMs + deltaMs));
          const snapped = resolveSnap(rawStart, candidates, thresholdMs);
          const newStart = snapped?.ms ?? rawStart;
          if (newStart < endMs - 100) {
            update(i, { startMs: newStart });
          }
        } else if (draggingRef.current === "end") {
          const rawEnd = Math.max(startMs + 100, Math.round(endMs + deltaMs));
          const snapped = resolveSnap(rawEnd, candidates, thresholdMs);
          const newEnd = snapped?.ms ?? rawEnd;
          // Re-clamp after snap so the snap target can't violate the
          // 100ms-min-duration invariant.
          update(i, { endMs: Math.max(startMs + 100, newEnd) });
        }
      };

      const handleUp = () => {
        // rowIndex commits live in handleMove so the visual position
        // tracks the cursor; no extra dispatch needed on pointerup.
        draggingRef.current = null;
        document.removeEventListener("pointermove", handleMove);
        document.removeEventListener("pointerup", handleUp);
      };

      document.addEventListener("pointermove", handleMove);
      document.addEventListener("pointerup", handleUp);
    },
    [subtitle.startMs, subtitle.endMs, index, onPushHistory],
  );

  return (
    <div
      className={cn(
        // 2026-05-18 — selected state was simplified to a fill-only
        // change. The previous outline ring + visible side resize bars
        // read as a heavy "edit handle" UI, but the operator only
        // wanted feedback that the row is active. Drag/resize is still
        // wired through the (now-invisible) 8px-wide edge zones below.
        "group absolute bottom-1 top-1 flex items-center overflow-hidden rounded-[10px]",
        // figma 2047:408685 (selected) — selected uses navy-100
        // (lighter highlight) so the active chip stands out without
        // dominating the row. Default keeps navy-300 from before.
        isSelected
          ? "z-10 bg-heimdex-navy-100 text-grayscale-900"
          : "bg-heimdex-navy-300 hover:brightness-110",
      )}
      style={{ left: leftPx, width: widthPx }}
      onClick={(e) => {
        e.stopPropagation();
        if (razorMode && onRazorSplit) {
          const rect = e.currentTarget.getBoundingClientRect();
          const offsetPx = e.clientX - rect.left;
          const durationMs = subtitle.endMs - subtitle.startMs;
          const rawMs = subtitle.startMs + (offsetPx / rect.width) * durationMs;
          const atMs = Math.round(rawMs / FRAME_MS) * FRAME_MS;
          onRazorSplit(atMs);
        } else {
          onSelect();
          onSeek?.(subtitle.startMs);
        }
      }}
    >
      {/* Left resize zone — invisible by default; hovering surfaces a
          2px white guide rail so the operator can find the edge. The
          zone itself is 8px wide (tap target), the visual rail is
          narrower so the block reads as a clean pill at rest. */}
      <div
        className="absolute bottom-1 left-0 top-1 z-20 w-2 cursor-col-resize after:absolute after:bottom-0 after:left-[3px] after:top-0 after:w-[2px] after:rounded-full after:bg-white/0 after:transition-colors hover:after:bg-white/70"
        onPointerDown={handlePointerDown("start")}
        aria-label="자막 시작 시간 조정"
      />

      {/* Draggable body */}
      <div
        className="flex-1 min-w-0 cursor-grab select-none px-[10px] py-[12px] active:cursor-grabbing"
        onPointerDown={handlePointerDown("move")}
      >
        {widthPx >= 20 && (
          // Hide text when the block narrows below ~20 px — even a
          // single Korean glyph barely fits at that width, so showing
          // it just produces flicker as the user zooms out. Matches
          // the 'zoom out to a full hour fits' UX target.
          <p
            className={cn(
              // Operator request 2026-05-24: auto-STT host subtitle
              // blocks render their text centred inside the box.
              // ``text-center`` combines cleanly with ``truncate``
              // (overflow:hidden + ellipsis + nowrap) — the visible
              // truncated portion stays centred in the available
              // width.
              "truncate text-center text-[14px] font-semibold leading-[1.4] tracking-[-0.35px]",
              // navy-100 (selected) is too light for white text →
              // switch to dark grayscale; navy-300 (default) stays
              // white as before.
              isSelected ? "text-grayscale-900" : "text-white",
            )}
          >
            {subtitle.text || "자막"}
          </p>
        )}
      </div>

      {/* Right resize zone — mirror of the left, same hover affordance. */}
      <div
        className="absolute bottom-1 right-0 top-1 z-20 w-2 cursor-col-resize after:absolute after:bottom-0 after:right-[3px] after:top-0 after:w-[2px] after:rounded-full after:bg-white/0 after:transition-colors hover:after:bg-white/70"
        aria-label="자막 종료 시간 조정"
        onPointerDown={handlePointerDown("end")}
      />
    </div>
  );
}
