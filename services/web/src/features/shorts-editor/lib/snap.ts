// Magnetic snapping for timeline drag/trim operations.
//
// Pattern ported from OpenCut (timeline/snapping/build.ts +
// resolve.ts + threshold.ts) — MIT-licensed. Adapted to our number-ms
// coordinate model (vs MediaTime/BigInt) and our zoom unit (px/sec
// vs ticks-per-second), but the source-builder + resolver split is the
// same: pluggable sources feed a flat SnapPoint[] that the resolver
// scans for the nearest hit within a zoom-aware threshold.

import type { EditorClip, EditorSubtitle } from "./types";

export type SnapPointKind =
  | "element-start"
  | "element-end"
  | "playhead"
  | "boundary"; // 0 ms or total duration

export interface SnapPoint {
  ms: number;
  kind: SnapPointKind;
  // Source element id when the snap originated from a draggable block.
  // Surfaces in the snap-indicator UI so the operator sees WHICH block
  // they're snapping to.
  sourceId?: string;
}

// 10 px is the operator-friendly pull radius for a snap. Stays the same
// in screen px so the gesture feel doesn't change as the operator
// zooms. We translate to ms inside resolveSnap so the resolver itself
// works in coordinate space.
const SNAP_THRESHOLD_PX = 10;

/**
 * Zoom-aware threshold in ms. At higher zoom (more px/sec) the same
 * 10-px reach maps to fewer ms; at low zoom it's the opposite. Floor
 * at 1 ms so 0-zoom edge cases don't blow up.
 */
export function getSnapThresholdMs(zoom: number): number {
  const safeZoom = Math.max(0.1, zoom);
  return Math.max(1, (SNAP_THRESHOLD_PX / safeZoom) * 1000);
}

interface SourceArgs {
  // The element currently being dragged — excluded from edge sources
  // so an element doesn't snap to itself.
  excludeId?: string;
  // Excluded subtitle index for the host subtitle channel (it's
  // index-addressed, not id).
  excludeSubtitleIndex?: number;
}

/**
 * Edge snap points from operator-added text overlays. Each overlay
 * contributes a start + end snap point. We use the projected
 * subtitle-shape array so callers don't need to know the overlay
 * type system; both shapes carry id/startMs/endMs.
 */
export function overlayEdgeSnapPoints(
  overlays: EditorSubtitle[],
  args: SourceArgs = {},
): SnapPoint[] {
  const out: SnapPoint[] = [];
  for (const o of overlays) {
    if (args.excludeId && o.id === args.excludeId) continue;
    out.push({ ms: o.startMs, kind: "element-start", sourceId: o.id });
    out.push({ ms: o.endMs, kind: "element-end", sourceId: o.id });
  }
  return out;
}

/**
 * Edge snap points from host auto-STT subtitles. Subtitles are
 * index-addressed in state.subtitles, so excludeId is irrelevant —
 * we exclude by index when the dragging block is a subtitle.
 */
export function subtitleEdgeSnapPoints(
  subtitles: EditorSubtitle[],
  args: SourceArgs = {},
): SnapPoint[] {
  const out: SnapPoint[] = [];
  for (let i = 0; i < subtitles.length; i++) {
    if (args.excludeSubtitleIndex === i) continue;
    const s = subtitles[i];
    out.push({ ms: s.startMs, kind: "element-start", sourceId: s.id });
    out.push({ ms: s.endMs, kind: "element-end", sourceId: s.id });
  }
  return out;
}

/**
 * Clip boundary snap points. Each clip's timeline position (start +
 * end) is a snap candidate — this is how trims line up with cuts.
 * ``excludeId`` lets the dragging clip skip its own edges so the
 * gesture doesn't lock to a zero-delta position.
 */
export function clipEdgeSnapPoints(
  clips: EditorClip[],
  args: SourceArgs = {},
): SnapPoint[] {
  const out: SnapPoint[] = [];
  for (const c of clips) {
    if (args.excludeId && c.id === args.excludeId) continue;
    const s = c.timelineStartMs;
    const e = c.timelineStartMs + (c.trimEndMs - c.trimStartMs);
    out.push({ ms: s, kind: "element-start", sourceId: c.id });
    out.push({ ms: e, kind: "element-end", sourceId: c.id });
  }
  return out;
}

export function playheadSnapPoint(playheadMs: number): SnapPoint {
  return { ms: playheadMs, kind: "playhead" };
}

export function boundarySnapPoints(totalMs: number): SnapPoint[] {
  return [
    { ms: 0, kind: "boundary" },
    { ms: totalMs, kind: "boundary" },
  ];
}

/**
 * Convenience wrapper for the playhead drag/click path: apply snap when
 * a hit lands within ``thresholdMs`` of ``targetMs``, otherwise pass the
 * value through unchanged. The TimelinePanel composes its snap pool +
 * threshold once per render and uses this to wrap ``onSeek``; a unit
 * test of this function locks the wrap's behaviour without needing to
 * render the panel itself (TimelinePanel still calls it inline so
 * removing the helper here would break that test).
 *
 * Returns the ms the caller should pass downstream — never null.
 */
export function applyPlayheadSnap(
  targetMs: number,
  snapPoints: SnapPoint[],
  thresholdMs: number,
): number {
  const hit = resolveSnap(targetMs, snapPoints, thresholdMs);
  return hit ? hit.ms : targetMs;
}

/**
 * Scan snap points for the nearest hit within ``thresholdMs``. Returns
 * the snapped ms + the matched SnapPoint (so the caller can paint a
 * snap indicator). Returns null when nothing's within reach so callers
 * can apply their plain target unchanged.
 */
export function resolveSnap(
  targetMs: number,
  snapPoints: SnapPoint[],
  thresholdMs: number,
): { ms: number; point: SnapPoint } | null {
  let best: SnapPoint | null = null;
  let bestDist = Infinity;
  for (const p of snapPoints) {
    const d = Math.abs(targetMs - p.ms);
    if (d <= thresholdMs && d < bestDist) {
      best = p;
      bestDist = d;
    }
  }
  return best ? { ms: best.ms, point: best } : null;
}
