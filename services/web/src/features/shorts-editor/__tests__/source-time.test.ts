import { describe, it, expect } from "vitest";
import { getSourceTime, getClipIndexAtTime, getActiveSubtitles, isSubtitleVisibleInClips, getVisibleSubtitles } from "../lib/source-time";
import { recomputeTimeline } from "../lib/timeline-math";
import type { EditorClip } from "../lib/types";

function makeClip(trimStart: number, trimEnd: number, videoId = "v1", id = "c"): EditorClip {
  return {
    id,
    sceneId: "s",
    videoId,
    sourceType: "gdrive",
    originalStartMs: trimStart,
    originalEndMs: trimEnd,
    trimStartMs: trimStart,
    trimEndMs: trimEnd,
    timelineStartMs: 0,
    volume: 1.0,
  };
}

describe("getSourceTime", () => {
  it("maps timeline position to source position in single clip", () => {
    const clips = recomputeTimeline([makeClip(5000, 10000, "v1", "c1")]);
    const result = getSourceTime(clips, 2000);

    expect(result).not.toBeNull();
    expect(result!.clipIndex).toBe(0);
    expect(result!.videoId).toBe("v1");
    expect(result!.sourceMs).toBe(7000); // 5000 + 2000
  });

  it("maps across multiple clips", () => {
    const clips = recomputeTimeline([
      makeClip(0, 3000, "v1", "c1"),
      makeClip(10000, 15000, "v2", "c2"),
    ]);

    // In clip 1
    const r1 = getSourceTime(clips, 1000);
    expect(r1!.clipIndex).toBe(0);
    expect(r1!.sourceMs).toBe(1000);

    // In clip 2 (timeline 3000 = start of clip 2)
    const r2 = getSourceTime(clips, 4000);
    expect(r2!.clipIndex).toBe(1);
    expect(r2!.videoId).toBe("v2");
    expect(r2!.sourceMs).toBe(11000); // 10000 + (4000-3000)
  });

  it("returns null for position past all clips", () => {
    const clips = recomputeTimeline([makeClip(0, 2000)]);
    expect(getSourceTime(clips, 5000)).toBeNull();
  });

  it("returns null for empty clips", () => {
    expect(getSourceTime([], 0)).toBeNull();
  });

  it("returns null at the totalDuration boundary (last clip's end is exclusive)", () => {
    // clip ranges use ``timelineMs < clipEnd`` (strict less-than),
    // so the exact end-of-timeline ms maps to no clip. The playback
    // sync layer depends on this — when the playhead reaches the
    // end the source-time lookup is null and the loop-back path in
    // usePlaybackSync.rAF takes over without trying to derive a
    // source-video position from a non-existent clip slot.
    const clips = recomputeTimeline([
      makeClip(0, 15000, "v1", "c1"),
      makeClip(0, 15000, "v1", "c2"),
    ]);
    expect(getSourceTime(clips, 30000)).toBeNull();
  });
});

describe("getClipIndexAtTime", () => {
  it("returns correct index", () => {
    const clips = recomputeTimeline([makeClip(0, 2000, "v", "a"), makeClip(0, 3000, "v", "b")]);
    expect(getClipIndexAtTime(clips, 0)).toBe(0);
    expect(getClipIndexAtTime(clips, 1999)).toBe(0);
    expect(getClipIndexAtTime(clips, 2000)).toBe(1);
    expect(getClipIndexAtTime(clips, 4999)).toBe(1);
  });

  it("returns -1 past end", () => {
    const clips = recomputeTimeline([makeClip(0, 1000)]);
    expect(getClipIndexAtTime(clips, 1000)).toBe(-1);
  });
});

describe("getActiveSubtitles", () => {
  it("returns subtitles within time range", () => {
    const subs = [
      { startMs: 0, endMs: 2000, text: "a" },
      { startMs: 1000, endMs: 3000, text: "b" },
      { startMs: 5000, endMs: 7000, text: "c" },
    ];

    expect(getActiveSubtitles(subs, 1500)).toHaveLength(2);
    expect(getActiveSubtitles(subs, 500)).toHaveLength(1);
    expect(getActiveSubtitles(subs, 4000)).toHaveLength(0);
    expect(getActiveSubtitles(subs, 6000)).toHaveLength(1);
  });

  it("returns empty for empty array", () => {
    expect(getActiveSubtitles([], 0)).toHaveLength(0);
  });
});

describe("isSubtitleVisibleInClips", () => {
  // 2026-05-26 — operator-reported gap: auto-STT routinely produces
  // utterances longer than a clip's visible window and the strict
  // fully-contained check used to hide every subtitle whose range
  // straddled an adjacent-clip boundary (e.g. 14980→17720 across
  // clip0 ending at 15000 + clip1 starting at 15000). The predicate
  // now uses an OVERLAP test, so a subtitle visible in any part of
  // any clip window is kept.
  it("returns true when subtitle falls fully within a clip", () => {
    const clips = recomputeTimeline([makeClip(0, 10000, "v1", "c1")]);
    expect(isSubtitleVisibleInClips({ startMs: 1000, endMs: 3000 }, clips)).toBe(true);
  });

  it("returns true when subtitle extends past clip end but starts inside (overlap)", () => {
    const clips = recomputeTimeline([makeClip(0, 5000, "v1", "c1")]);
    // Subtitle starts at 4000 (inside clip) and ends at 7000 (past clip
    // end at 5000). The visible portion 4000-5000 is real screen time
    // and used to be erased by the fully-contained predicate.
    expect(isSubtitleVisibleInClips({ startMs: 4000, endMs: 7000 }, clips)).toBe(true);
  });

  it("returns true when subtitle starts before clip start but ends inside (overlap)", () => {
    const clips = [{ ...makeClip(0, 5000, "v1", "c1"), timelineStartMs: 2000 }];
    // Clip window in timeline coords = [2000, 7000). Subtitle 1000-3000
    // overlaps the [2000, 3000) slice and must be visible.
    expect(isSubtitleVisibleInClips({ startMs: 1000, endMs: 3000 }, clips)).toBe(true);
  });

  it("returns true for a subtitle that straddles two adjacent clips' boundary", () => {
    // Reproduces the operator's environment: clip0 [0,15000), clip1
    // [15000,30000). Subtitle 14980-17720 straddles the 15000 boundary
    // and was previously hidden because no single clip fully contained
    // it. The overlap predicate must keep it visible.
    const clips = recomputeTimeline([
      makeClip(0, 15000, "v1", "c1"),
      makeClip(0, 15000, "v1", "c2"),
    ]);
    expect(
      isSubtitleVisibleInClips({ startMs: 14980, endMs: 17720 }, clips),
    ).toBe(true);
  });

  it("returns true when subtitle fits in any of multiple clips", () => {
    const clips = recomputeTimeline([
      makeClip(0, 3000, "v1", "c1"),
      makeClip(0, 5000, "v1", "c2"),
    ]);
    // Subtitle at 4000-6000 falls within clip 2 (timeline 3000-8000)
    expect(isSubtitleVisibleInClips({ startMs: 4000, endMs: 6000 }, clips)).toBe(true);
  });

  it("returns false when the subtitle window is entirely outside every clip", () => {
    // Trim semantics still work: a subtitle whose entire [start, end)
    // range falls outside every clip window stays hidden.
    const clips = [{ ...makeClip(0, 5000, "v1", "c1"), timelineStartMs: 0 }];
    expect(
      isSubtitleVisibleInClips({ startMs: 6000, endMs: 8000 }, clips),
    ).toBe(false);
  });

  it("returns false for empty clips", () => {
    expect(isSubtitleVisibleInClips({ startMs: 0, endMs: 1000 }, [])).toBe(false);
  });
});

describe("getVisibleSubtitles", () => {
  it("trim shrink hides out-of-range subtitles, grow-back restores them", () => {
    // Setup: clip [0, 10000] with three subtitles. 2026-05-26 — the
    // visibility predicate is now overlap-based, so subtitle "b" at
    // 4000-6000 stays visible after trimming to [0, 5000] because the
    // [4000,5000) slice still falls inside the clip window. Subtitle
    // "c" at 7000-9000 sits entirely past the trimmed end and stays
    // hidden, which is the trim semantic we still care about.
    const clips = recomputeTimeline([makeClip(0, 10000, "v1", "c1")]);
    const subs = [
      { startMs: 1000, endMs: 3000, text: "a" },
      { startMs: 4000, endMs: 6000, text: "b" },
      { startMs: 7000, endMs: 9000, text: "c" },
    ];

    // All visible initially
    expect(getVisibleSubtitles(subs, clips)).toHaveLength(3);

    // Trim right handle to [0, 5000] — "a" entirely inside, "b"
    // overlaps the trimmed window, "c" entirely outside.
    const trimmedClips = [{ ...clips[0], trimEndMs: 5000 }];
    const visible = getVisibleSubtitles(subs, trimmedClips);
    expect(visible.map((s) => s.text).sort()).toEqual(["a", "b"]);

    // Grow back to [0, 10000] — all three restored
    const restoredClips = [{ ...clips[0], trimEndMs: 10000 }];
    expect(getVisibleSubtitles(subs, restoredClips)).toHaveLength(3);
  });

  it("subtitle timestamps are unchanged after trim", () => {
    const clips = recomputeTimeline([makeClip(0, 10000, "v1", "c1")]);
    const subs = [
      // Use a subtitle entirely outside the trimmed window so the
      // overlap predicate still hides it — the assertion here is about
      // preserving original timestamps, not which subtitles render.
      { startMs: 7000, endMs: 9000, text: "c" },
    ];
    const trimmedClips = [{ ...clips[0], trimEndMs: 5000 }];
    const visible = getVisibleSubtitles(subs, trimmedClips);
    expect(visible).toHaveLength(0);
    // Original still has its timestamps
    expect(subs[0].startMs).toBe(7000);
    expect(subs[0].endMs).toBe(9000);
  });
});

describe("MOVE_CLIP behavior (via getVisibleSubtitles)", () => {
  it("moved clip changes which subtitles are visible", () => {
    // Clip at [0, 5000]
    const clips = [{ ...makeClip(0, 5000, "v1", "c1"), timelineStartMs: 0 }];
    const subs = [
      { startMs: 1000, endMs: 3000, text: "in-range" },
      { startMs: 6000, endMs: 8000, text: "out-of-range" },
    ];
    expect(getVisibleSubtitles(subs, clips)).toHaveLength(1);

    // Move clip to start at 5000 → window is [5000, 10000]
    const movedClips = [{ ...clips[0], timelineStartMs: 5000 }];
    const visible = getVisibleSubtitles(subs, movedClips);
    expect(visible).toHaveLength(1);
    expect(visible[0].text).toBe("out-of-range");
  });
});
