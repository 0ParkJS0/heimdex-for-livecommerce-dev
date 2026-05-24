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
