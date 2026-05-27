import type { EditorClip } from "./types";

export {
  msToPixels,
  pixelsToMs,
  snapToGrid,
  formatTimelineTimestamp,
  formatVideoTimestampHMS,
} from "@/lib/timeline";

export function getClipDuration(clip: EditorClip): number {
  return clip.trimEndMs - clip.trimStartMs;
}

/**
 * Pack clips back-to-back starting from offset 0. Used ONLY during
 * initial load (INIT_FROM_SCENES / INIT_FROM_COMPOSITION) to establish
 * the initial packed layout. After initialization, clips keep their
 * own timelineStartMs — gaps between clips are allowed and clips can
 * be repositioned via MOVE_CLIP.
 */
export function recomputeTimeline(clips: EditorClip[]): EditorClip[] {
  let offset = 0;
  return clips.map((clip) => {
    const updated = { ...clip, timelineStartMs: offset };
    offset += getClipDuration(clip);
    return updated;
  });
}

/**
 * Total duration = the furthest clip end across all clips.
 * Accounts for gaps between clips (clips may not be packed).
 */
export function getTotalDuration(clips: EditorClip[]): number {
  if (clips.length === 0) return 0;
  let maxEnd = 0;
  for (const clip of clips) {
    const end = clip.timelineStartMs + getClipDuration(clip);
    if (end > maxEnd) maxEnd = end;
  }
  return maxEnd;
}

/**
 * Width of a timeline track lane in px.
 *
 * B12 (2026-05-26): without the ``Math.max`` clamp a short clip
 * (totalDurationMs * zoom < containerWidth) drew the SubtitleTrack /
 * ClipTrack background only as far as ``totalWidth``, while the
 * TimelineRuler extended its tick labels out to ``containerWidth``.
 * The mismatch surfaced as empty lanes from ~30-40 % of the timeline
 * view onward — the operator-reported "playhead keeps moving past the
 * blocks but the rows look blank past that point". Clamping every lane
 * to at least ``containerWidthPx`` keeps the lane background visible
 * across the full ruler extent. When the caller does not yet know the
 * container width (mount before ResizeObserver fires) we fall back to
 * the content extent.
 *
 * NOTE: this only sets the lane *background* width. Block positions
 * still come from ``msToPixels(block.startMs)`` — the function does
 * not move blocks, just keeps the lane painted under the ruler.
 */
export function computeTrackLaneWidth(
  totalDurationMs: number,
  zoom: number,
  containerWidthPx: number | null | undefined,
): number {
  const totalWidth = Math.max(0, totalDurationMs) * (zoom / 1000);
  if (containerWidthPx == null || containerWidthPx <= 0) return totalWidth;
  return Math.max(totalWidth, containerWidthPx);
}
