import type { EditorClip, EditorSubtitle } from "./types";

// Helpers that enforce the 1:1 clip ↔ subtitle linkage rule atomically
// inside the reducer. Each function is a pure array transform so callers
// (reducer cases) can use them without side effects.

// ── Proportional text split ───────────────────────────────────────────────

/**
 * Split subtitle text at a proportional position (0..1). Finds the
 * nearest Korean eojeol (space) boundary at or before the target
 * character index so the split lands on a natural word break. Falls
 * back to a raw glyph-position split when no space exists (single-
 * eojeol subtitles like "축하드립니다").
 *
 * Heuristic — will be replaced with word-level STT boundaries when
 * that data becomes available.
 */
export function splitSubtitleText(
  text: string,
  fraction: number,
): [string, string] {
  if (!text || text.length === 0) return ["", ""];
  if (fraction <= 0) return ["", text];
  if (fraction >= 1) return [text, ""];

  const targetIdx = Math.round(text.length * fraction);

  // Find the nearest space at or before targetIdx for eojeol-aware split.
  let splitAt = -1;
  for (let i = Math.min(targetIdx, text.length - 1); i >= 0; i--) {
    if (text[i] === " ") {
      splitAt = i;
      break;
    }
  }

  // If no space found before targetIdx, search forward.
  if (splitAt < 0) {
    for (let i = targetIdx + 1; i < text.length; i++) {
      if (text[i] === " ") {
        splitAt = i;
        break;
      }
    }
  }

  // Eojeol boundary found — split at the space, trimming the space itself.
  if (splitAt >= 0 && splitAt > 0 && splitAt < text.length) {
    return [text.slice(0, splitAt).trimEnd(), text.slice(splitAt).trimStart()];
  }

  // No space at all — fall back to raw glyph split.
  const glyphIdx = Math.max(1, Math.min(text.length - 1, targetIdx));
  return [text.slice(0, glyphIdx), text.slice(glyphIdx)];
}

// ── Subtitle split ────────────────────────────────────────────────────────

/**
 * Split any subtitle that straddles `atMs` and falls within
 * `[clipStart, clipEnd)`. Subtitles fully outside that window are
 * returned unchanged. Each half receives a proportional slice of
 * the original text based on the time-position of the cut.
 */
export function splitSubtitlesAtMs(
  subs: EditorSubtitle[],
  atMs: number,
  clipRange: [number, number],
): EditorSubtitle[] {
  const [clipStart, clipEnd] = clipRange;
  const result: EditorSubtitle[] = [];
  for (const sub of subs) {
    const straddles = sub.startMs < atMs && atMs < sub.endMs;
    const withinClip = sub.startMs < clipEnd && sub.endMs > clipStart;
    if (straddles && withinClip) {
      const duration = sub.endMs - sub.startMs;
      const fraction = duration > 0 ? (atMs - sub.startMs) / duration : 0.5;
      const [headText, tailText] = splitSubtitleText(sub.text, fraction);
      result.push({ ...sub, text: headText, endMs: atMs });
      result.push({ ...sub, id: generateLinkedSubId(), text: tailText, startMs: atMs });
    } else {
      result.push(sub);
    }
  }
  return result;
}

// ── Clip split ────────────────────────────────────────────────────────────

/**
 * Split any clip whose composition window `[timelineStartMs, timelineStartMs +
 * duration)` straddles `atMs`. The split uses the same source-coord math
 * as SPLIT_CLIP in the reducer.
 */
export function splitClipsAtMs(
  clips: EditorClip[],
  atMs: number,
): EditorClip[] {
  const result: EditorClip[] = [];
  for (const clip of clips) {
    const clipStart = clip.timelineStartMs;
    const clipEnd = clipStart + (clip.trimEndMs - clip.trimStartMs);
    if (atMs > clipStart && atMs < clipEnd) {
      const sourceCut = clip.trimStartMs + (atMs - clipStart);
      result.push({ ...clip, trimEndMs: sourceCut });
      result.push({
        ...clip,
        id: generateLinkedClipId(),
        trimStartMs: sourceCut,
        timelineStartMs: atMs,
      });
    } else {
      result.push(clip);
    }
  }
  return result;
}

// ── Drop + shift after REMOVE_CLIP ───────────────────────────────────────

/**
 * After a clip is removed from `[removeStart, removeEnd)`:
 *  - Drop subtitles fully inside the removed window.
 *  - Trim subtitles that straddle either edge.
 *  - Shift all remaining subtitles that start at or after `removeEnd`
 *    left by `(removeEnd - removeStart)`.
 */
export function dropAndShiftSubtitles(
  subs: EditorSubtitle[],
  removeStart: number,
  removeEnd: number,
): EditorSubtitle[] {
  const removedDuration = removeEnd - removeStart;
  const result: EditorSubtitle[] = [];

  for (const sub of subs) {
    // Fully inside the removed window — drop.
    if (sub.startMs >= removeStart && sub.endMs <= removeEnd) {
      continue;
    }

    // Fully after — shift left.
    if (sub.startMs >= removeEnd) {
      result.push({
        ...sub,
        startMs: sub.startMs - removedDuration,
        endMs: sub.endMs - removedDuration,
      });
      continue;
    }

    // Fully before — keep as-is.
    if (sub.endMs <= removeStart) {
      result.push(sub);
      continue;
    }

    // Straddles removeStart only (starts before, ends inside or after).
    if (sub.startMs < removeStart && sub.endMs > removeStart) {
      const newEnd = sub.endMs > removeEnd
        // Subtitle spans beyond the removed window: trim the gap out.
        ? sub.endMs - removedDuration
        : removeStart;
      if (newEnd > sub.startMs) {
        result.push({ ...sub, endMs: newEnd });
      }
      continue;
    }

    // Straddles removeEnd only (starts inside, ends after).
    if (sub.startMs >= removeStart && sub.startMs < removeEnd && sub.endMs > removeEnd) {
      result.push({
        ...sub,
        startMs: removeStart,
        endMs: sub.endMs - removedDuration,
      });
      continue;
    }

    result.push(sub);
  }

  return result;
}

/**
 * After a subtitle block is removed from `[removeStart, removeEnd)`:
 *  - Drop clips whose composition window is fully inside the removed range.
 *  - Trim straddling clips by adjusting trim bounds.
 *  - Shift clips that start at or after `removeEnd` left by the removed
 *    duration. `timelineStartMs` is rewritten; `trimStartMs`/`trimEndMs`
 *    are NOT changed — they are source-video coords, not timeline coords.
 *
 * NOTE: Implemented conservatively — fully-contained clips are dropped.
 * The operator confirmed the linkage is intentional (Task 3 spec).
 */
export function dropAndShiftClips(
  clips: EditorClip[],
  removeStart: number,
  removeEnd: number,
): EditorClip[] {
  const removedDuration = removeEnd - removeStart;
  const result: EditorClip[] = [];

  for (const clip of clips) {
    const clipStart = clip.timelineStartMs;
    const clipEnd = clipStart + (clip.trimEndMs - clip.trimStartMs);

    // Fully inside the removed window — drop.
    if (clipStart >= removeStart && clipEnd <= removeEnd) {
      continue;
    }

    // Fully after — shift left.
    if (clipStart >= removeEnd) {
      result.push({ ...clip, timelineStartMs: clip.timelineStartMs - removedDuration });
      continue;
    }

    // Fully before — keep as-is.
    if (clipEnd <= removeStart) {
      result.push(clip);
      continue;
    }

    // Straddles removeStart (clip starts before, ends inside removed zone).
    if (clipStart < removeStart && clipEnd > removeStart && clipEnd <= removeEnd) {
      const trimAmount = clipEnd - removeStart;
      const newTrimEnd = clip.trimEndMs - trimAmount;
      if (newTrimEnd > clip.trimStartMs) {
        result.push({ ...clip, trimEndMs: newTrimEnd });
      }
      continue;
    }

    // Straddles removeEnd (clip starts inside, ends after removed zone).
    if (clipStart >= removeStart && clipStart < removeEnd && clipEnd > removeEnd) {
      const overlapMs = removeEnd - clipStart;
      result.push({
        ...clip,
        trimStartMs: clip.trimStartMs + overlapMs,
        timelineStartMs: removeStart,
      });
      continue;
    }

    // Fully spans the removed window (clip start < removeStart AND clip end > removeEnd).
    if (clipStart < removeStart && clipEnd > removeEnd) {
      // Trim the middle out: the clip shrinks by removedDuration.
      const newTrimEnd = clip.trimEndMs - removedDuration;
      if (newTrimEnd > clip.trimStartMs) {
        result.push({ ...clip, trimEndMs: newTrimEnd });
      }
      continue;
    }

    result.push(clip);
  }

  return result;
}

// ── TRIM_CLIP cascade ───────────────────────────────────────────────────

/**
 * Non-destructive trim pass-through. When a clip is trimmed, subtitles
 * are NOT dropped, clamped, or shifted — their original timestamps are
 * preserved so extending the trim back makes them reappear.
 *
 * Visibility of subtitles outside the current clip window is handled
 * at render time by getVisibleSubtitles / isSubtitleVisibleInClips
 * (clip-window filtering in source-time.ts).
 *
 * Gaps between clips are allowed (Bug 2 spec), so downstream subtitles
 * are NOT shifted — they keep their original absolute positions.
 *
 * TODO: revisit when word-level timestamps land — proportional text
 * slicing could be applied to subtitles that straddle a trim edge.
 */
export function trimClipSubtitles(
  subs: EditorSubtitle[],
  _oldStart: number,
  _oldEnd: number,
  _newStart: number,
  _newEnd: number,
): EditorSubtitle[] {
  // Non-destructive: return subtitles unchanged. Render-time filtering
  // (getVisibleSubtitles) hides subtitles outside clip windows.
  return subs;
}

// ── ID generators ─────────────────────────────────────────────────────────

let _linkedSubCounter = 0;
function generateLinkedSubId(): string {
  return `sub_link_${Date.now()}_${++_linkedSubCounter}`;
}

let _linkedClipCounter = 0;
function generateLinkedClipId(): string {
  return `clip_link_${Date.now()}_${++_linkedClipCounter}`;
}
