import { describe, it, expect } from "vitest";
import {
  computeTrackLaneWidth,
  msToPixels,
  pixelsToMs,
  snapToGrid,
  getClipDuration,
  recomputeTimeline,
  getTotalDuration,
  formatTimelineTimestamp,
} from "../lib/timeline-math";
import type { EditorClip } from "../lib/types";

function makeClip(trimStart: number, trimEnd: number, id = "c"): EditorClip {
  return {
    id,
    sceneId: "s",
    videoId: "v",
    sourceType: "gdrive",
    originalStartMs: trimStart,
    originalEndMs: trimEnd,
    trimStartMs: trimStart,
    trimEndMs: trimEnd,
    timelineStartMs: 0,
    volume: 1.0,
  };
}

describe("msToPixels / pixelsToMs", () => {
  it("converts at default zoom (100 px/s)", () => {
    expect(msToPixels(1000, 100)).toBe(100);
    expect(msToPixels(2500, 100)).toBe(250);
    expect(pixelsToMs(100, 100)).toBe(1000);
    expect(pixelsToMs(250, 100)).toBe(2500);
  });

  it("converts at different zoom levels", () => {
    expect(msToPixels(1000, 50)).toBe(50);
    expect(msToPixels(1000, 200)).toBe(200);
    expect(pixelsToMs(50, 50)).toBe(1000);
  });

  it("handles zero zoom gracefully", () => {
    expect(pixelsToMs(100, 0)).toBe(0);
  });

  it("handles zero ms", () => {
    expect(msToPixels(0, 100)).toBe(0);
  });
});

describe("snapToGrid", () => {
  it("snaps to nearest grid point", () => {
    expect(snapToGrid(1200, 1000)).toBe(1000);
    expect(snapToGrid(1600, 1000)).toBe(2000);
    expect(snapToGrid(1500, 1000)).toBe(2000);
  });

  it("returns exact value when on grid", () => {
    expect(snapToGrid(3000, 1000)).toBe(3000);
  });

  it("returns input when gridMs is 0", () => {
    expect(snapToGrid(1234, 0)).toBe(1234);
  });
});

describe("getClipDuration", () => {
  it("returns trimmed duration", () => {
    const clip = makeClip(1000, 4000);
    expect(getClipDuration(clip)).toBe(3000);
  });
});

describe("recomputeTimeline", () => {
  it("assigns sequential timeline positions", () => {
    const clips = [makeClip(0, 2000, "a"), makeClip(5000, 8000, "b"), makeClip(0, 1000, "c")];
    const result = recomputeTimeline(clips);

    expect(result[0].timelineStartMs).toBe(0);
    expect(result[1].timelineStartMs).toBe(2000);
    expect(result[2].timelineStartMs).toBe(5000);
  });

  it("handles empty array", () => {
    expect(recomputeTimeline([])).toEqual([]);
  });

  it("handles single clip", () => {
    const result = recomputeTimeline([makeClip(100, 500)]);
    expect(result[0].timelineStartMs).toBe(0);
  });
});

describe("getTotalDuration", () => {
  it("returns sum of all clip durations", () => {
    const clips = recomputeTimeline([makeClip(0, 2000), makeClip(0, 3000)]);
    expect(getTotalDuration(clips)).toBe(5000);
  });

  it("returns 0 for empty array", () => {
    expect(getTotalDuration([])).toBe(0);
  });
});

describe("formatTimelineTimestamp", () => {
  it("formats seconds", () => {
    expect(formatTimelineTimestamp(0)).toBe("0:00");
    expect(formatTimelineTimestamp(5000)).toBe("0:05");
    expect(formatTimelineTimestamp(65000)).toBe("1:05");
  });

  it("formats with hours when needed", () => {
    expect(formatTimelineTimestamp(3661000)).toBe("1:01:01");
  });
});

// B12 (2026-05-26) — lane background widens to at least containerWidthPx
// so short clips don't leave SubtitleTrack/ClipTrack/TextOverlay lanes
// blank past totalDurationMs while the ruler keeps extending tick
// labels out across the viewport.
describe("computeTrackLaneWidth", () => {
  it("returns the content extent when no container width is supplied", () => {
    // 10s at 100 px/s = 1000 px
    expect(computeTrackLaneWidth(10_000, 100, null)).toBe(1000);
    expect(computeTrackLaneWidth(10_000, 100, undefined)).toBe(1000);
    expect(computeTrackLaneWidth(10_000, 100, 0)).toBe(1000);
  });

  it("clamps lane width to containerWidthPx when content is shorter", () => {
    // 5s at 100 px/s = 500 px, viewport says 1300 → clamp to 1300
    expect(computeTrackLaneWidth(5_000, 100, 1300)).toBe(1300);
  });

  it("returns the content extent when content is wider than the viewport", () => {
    // 60s at 100 px/s = 6000 px, viewport says 1300 → 6000 wins
    expect(computeTrackLaneWidth(60_000, 100, 1300)).toBe(6000);
  });

  it("zero-duration falls back to containerWidthPx (lane still paints)", () => {
    expect(computeTrackLaneWidth(0, 100, 800)).toBe(800);
    // No container either → genuinely empty lane.
    expect(computeTrackLaneWidth(0, 100, null)).toBe(0);
  });
});
