"use client";

// figma: 1713:271669  (cache: .figma-cache/1713-271669_phase5_editor-1.api.json)
// node-name: Subtitle Block · spec: Block 자막 미리보기 fs=10 fw=500 → text-[10px] font-medium
import { useCallback, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { EditorSubtitle } from "../lib/types";
import { msToPixels, pixelsToMs } from "../lib/timeline-math";

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
}

export function SubtitleBlock({
  subtitle,
  index,
  zoom,
  isSelected,
  onSelect,
  onUpdate,
  onSeek,
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

  // Latest callback/zoom mirrored into refs so the document-level
  // handler always reads fresh values without subscribing to them.
  const onUpdateRef = useRef(onUpdate);
  const zoomRef = useRef(zoom);
  const indexRef = useRef(index);
  useEffect(() => {
    onUpdateRef.current = onUpdate;
    zoomRef.current = zoom;
    indexRef.current = index;
  });

  const handlePointerDown = useCallback(
    (mode: "move" | "start" | "end") => (e: React.PointerEvent) => {
      e.stopPropagation();
      draggingRef.current = mode;
      startXRef.current = e.clientX;
      startValuesRef.current = {
        startMs: subtitle.startMs,
        endMs: subtitle.endMs,
      };

      const handleMove = (ev: PointerEvent) => {
        if (!draggingRef.current) return;
        const dx = ev.clientX - startXRef.current;
        const deltaMs = pixelsToMs(dx, zoomRef.current);
        const { startMs, endMs } = startValuesRef.current;
        const i = indexRef.current;
        const update = onUpdateRef.current;

        if (draggingRef.current === "move") {
          const newStart = Math.max(0, Math.round(startMs + deltaMs));
          const duration = endMs - startMs;
          update(i, { startMs: newStart, endMs: newStart + duration });
        } else if (draggingRef.current === "start") {
          const newStart = Math.max(0, Math.round(startMs + deltaMs));
          if (newStart < endMs - 100) {
            update(i, { startMs: newStart });
          }
        } else if (draggingRef.current === "end") {
          const newEnd = Math.max(startMs + 100, Math.round(endMs + deltaMs));
          update(i, { endMs: newEnd });
        }
      };

      const handleUp = () => {
        draggingRef.current = null;
        document.removeEventListener("pointermove", handleMove);
        document.removeEventListener("pointerup", handleUp);
      };

      document.addEventListener("pointermove", handleMove);
      document.addEventListener("pointerup", handleUp);
    },
    [subtitle.startMs, subtitle.endMs],
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
        isSelected
          ? "z-10 bg-heimdex-navy-500"
          : "bg-heimdex-navy-300 hover:brightness-110",
      )}
      style={{ left: leftPx, width: widthPx }}
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
        onSeek?.(subtitle.startMs);
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
        {widthPx > 30 && (
          <p className="truncate text-[14px] font-semibold leading-[1.4] tracking-[-0.35px] text-white">
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
