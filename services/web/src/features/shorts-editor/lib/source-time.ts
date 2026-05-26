import type { EditorClip } from "./types";
import { getClipDuration } from "./timeline-math";

export interface SourceTimeResult {
  clipIndex: number;
  videoId: string;
  sourceType: string;
  sourceMs: number;
}

/**
 * Map a timeline position to the source video position.
 * Returns null if the position is outside all clips (gap or past end).
 */
export function getSourceTime(
  clips: EditorClip[],
  timelineMs: number,
): SourceTimeResult | null {
  for (let i = 0; i < clips.length; i++) {
    const clip = clips[i];
    const clipEnd = clip.timelineStartMs + getClipDuration(clip);

    if (timelineMs >= clip.timelineStartMs && timelineMs < clipEnd) {
      const offsetInClip = timelineMs - clip.timelineStartMs;
      return {
        clipIndex: i,
        videoId: clip.videoId,
        sourceType: clip.sourceType,
        sourceMs: clip.trimStartMs + offsetInClip,
      };
    }
  }
  return null;
}

/**
 * Find the clip index at a given timeline position.
 * Returns -1 if no clip is found.
 */
export function getClipIndexAtTime(clips: EditorClip[], timelineMs: number): number {
  for (let i = 0; i < clips.length; i++) {
    const clip = clips[i];
    const clipEnd = clip.timelineStartMs + getClipDuration(clip);
    if (timelineMs >= clip.timelineStartMs && timelineMs < clipEnd) {
      return i;
    }
  }
  return -1;
}

/**
 * Get all subtitles active at a given timeline position.
 */
export function getActiveSubtitles<T extends { startMs: number; endMs: number }>(
  subtitles: T[],
  timelineMs: number,
): T[] {
  return subtitles.filter((s) => timelineMs >= s.startMs && timelineMs < s.endMs);
}

/**
 * Check whether a subtitle falls fully within at least one clip's
 * visible window. A clip's visible window is
 * `[clip.timelineStartMs, clip.timelineStartMs + clipDuration)`.
 *
 * Used at render time so trimming a clip hides subtitles outside
 * the new window WITHOUT deleting them — extending the trim back
 * restores them automatically.
 */
export function isSubtitleVisibleInClips<T extends { startMs: number; endMs: number }>(
  sub: T,
  clips: EditorClip[],
): boolean {
  // 2026-05-26 — operator-reported gap: subtitles whose [startMs, endMs)
  // straddles a clip boundary (e.g. 14980 → 17720 over a 15000ms cut)
  // were being filtered out because the previous predicate required
  // FULL containment inside a single clip. Auto-STT routinely produces
  // utterances longer than a clip's visible window, so the strict check
  // erased real subtitles from the timeline (visible during static
  // scrub, blank during auto-scroll past the cut).
  //
  // The render-time intent is "hide subtitles that don't overlap any
  // visible clip at all" — i.e. an OVERLAP test, not containment. A
  // subtitle whose end > clip.start AND start < clip.end has at least
  // one millisecond of presence inside the clip's window.
  return clips.some((clip) => {
    const clipEnd = clip.timelineStartMs + getClipDuration(clip);
    return sub.endMs > clip.timelineStartMs && sub.startMs < clipEnd;
  });
}

/**
 * Return only subtitles whose time range falls fully within at least
 * one clip's visible window. Subtitles outside all clip windows are
 * filtered out (hidden, not deleted).
 */
export function getVisibleSubtitles<T extends { startMs: number; endMs: number }>(
  subtitles: T[],
  clips: EditorClip[],
): T[] {
  return subtitles.filter((s) => isSubtitleVisibleInClips(s, clips));
}
