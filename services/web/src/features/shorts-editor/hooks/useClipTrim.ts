import { useCallback, useRef, useEffect } from "react";
import type { EditorClip } from "../lib/types";
import { pixelsToMs } from "../lib/timeline-math";
import { getSnapThresholdMs, resolveSnap, type SnapPoint } from "./../lib/snap";

type TrimEdge = "start" | "end";

interface UseClipTrimOptions {
  clip: EditorClip;
  clipIndex: number;
  zoom: number;
  onTrim: (index: number, trimStartMs?: number, trimEndMs?: number) => void;
  // Magnetic snap targets in TIMELINE coords. Hook converts the
  // dragged trim value (source coords) to timeline coords, resolves
  // the snap there, then converts back so the operator can latch the
  // clip edge onto subtitle edges / playhead / neighbor clips.
  snapPoints?: SnapPoint[];
}

/**
 * Pointer-event based trim handle interaction.
 * Returns onPointerDown handlers for left (start) and right (end) trim handles.
 */
export function useClipTrim({ clip, clipIndex, zoom, onTrim, snapPoints }: UseClipTrimOptions) {
  const startXRef = useRef(0);
  const startValueRef = useRef(0);
  const edgeRef = useRef<TrimEdge>("start");
  const snapRef = useRef<SnapPoint[] | undefined>(snapPoints);
  const clipRef = useRef(clip);
  const zoomRef = useRef(zoom);
  useEffect(() => {
    snapRef.current = snapPoints;
    clipRef.current = clip;
    zoomRef.current = zoom;
  });

  const onPointerMove = useCallback(
    (e: PointerEvent) => {
      const z = zoomRef.current;
      const c = clipRef.current;
      const dx = e.clientX - startXRef.current;
      const deltaMs = pixelsToMs(dx, z);
      let newValue = startValueRef.current + deltaMs;

      // Convert the proposed source-coord trim value to its TIMELINE
      // coord, snap there (subtitle edges, neighbor clips, playhead,
      // boundaries — all timeline-coord), and convert back.
      const candidates = (snapRef.current ?? []).filter(
        (p) => p.sourceId !== c.id,
      );
      if (candidates.length > 0) {
        const threshold = getSnapThresholdMs(z);
        const sourceToTimeline = (sourceMs: number) =>
          c.timelineStartMs + (sourceMs - c.trimStartMs);
        const timelineToSource = (timelineMs: number) =>
          c.trimStartMs + (timelineMs - c.timelineStartMs);
        const targetTimelineMs = sourceToTimeline(newValue);
        const snapped = resolveSnap(targetTimelineMs, candidates, threshold);
        if (snapped) newValue = timelineToSource(snapped.ms);
      }

      if (edgeRef.current === "start") {
        onTrim(clipIndex, Math.round(newValue), undefined);
      } else {
        onTrim(clipIndex, undefined, Math.round(newValue));
      }
    },
    [clipIndex, onTrim],
  );

  const onPointerUp = useCallback(
    (e: PointerEvent) => {
      (e.target as HTMLElement)?.releasePointerCapture?.(e.pointerId);
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
    },
    [onPointerMove],
  );

  const createHandleDown = useCallback(
    (edge: TrimEdge) => (e: React.PointerEvent) => {
      e.stopPropagation();
      e.preventDefault();
      (e.target as HTMLElement).setPointerCapture(e.pointerId);

      startXRef.current = e.clientX;
      edgeRef.current = edge;
      startValueRef.current = edge === "start" ? clip.trimStartMs : clip.trimEndMs;

      document.addEventListener("pointermove", onPointerMove);
      document.addEventListener("pointerup", onPointerUp);
    },
    [clip.trimStartMs, clip.trimEndMs, onPointerMove, onPointerUp],
  );

  // Cleanup on unmount if drag was in progress
  useEffect(() => {
    return () => {
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
    };
  }, [onPointerMove, onPointerUp]);

  return {
    onTrimStartDown: createHandleDown("start"),
    onTrimEndDown: createHandleDown("end"),
  };
}
