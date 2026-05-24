import { describe, it, expect } from "vitest";

import {
  getSnapThresholdMs,
  resolveSnap,
  overlayEdgeSnapPoints,
  subtitleEdgeSnapPoints,
  clipEdgeSnapPoints,
  playheadSnapPoint,
  boundarySnapPoints,
  type SnapPoint,
} from "../lib/snap";

describe("snap — threshold", () => {
  it("translates 10px pull radius to ms based on zoom", () => {
    // 100 px/sec → 10px = 100ms
    expect(getSnapThresholdMs(100)).toBeCloseTo(100, 1);
    // 50 px/sec → 10px = 200ms
    expect(getSnapThresholdMs(50)).toBeCloseTo(200, 1);
    // 200 px/sec → 10px = 50ms
    expect(getSnapThresholdMs(200)).toBeCloseTo(50, 1);
  });

  it("floors threshold at 1ms so 0-zoom edge cases don't explode", () => {
    expect(getSnapThresholdMs(0)).toBe(100_000); // safe-zoom 0.1 → 100_000
    // Very high zoom shrinks toward floor
    expect(getSnapThresholdMs(1_000_000)).toBeGreaterThanOrEqual(1);
  });
});

describe("snap — resolveSnap", () => {
  const points: SnapPoint[] = [
    { ms: 0, kind: "boundary" },
    { ms: 1_000, kind: "element-start", sourceId: "a" },
    { ms: 2_500, kind: "element-end", sourceId: "a" },
    { ms: 5_000, kind: "playhead" },
  ];

  it("returns null when nothing is within threshold", () => {
    expect(resolveSnap(3_500, points, 100)).toBeNull();
  });

  it("snaps to the nearest point within threshold", () => {
    // 1_050 is 50ms from element-start at 1_000
    const r = resolveSnap(1_050, points, 100);
    expect(r?.ms).toBe(1_000);
    expect(r?.point.kind).toBe("element-start");
  });

  it("prefers the closer of two candidates inside the threshold band", () => {
    // 4_950 is 50ms before playhead (5_000) and 2_450ms after element-end
    // (2_500). Both inside a generous threshold; playhead wins.
    const r = resolveSnap(4_950, points, 100);
    expect(r?.ms).toBe(5_000);
    expect(r?.point.kind).toBe("playhead");
  });

  it("snaps exactly when target IS a snap point", () => {
    expect(resolveSnap(0, points, 1)?.ms).toBe(0);
  });
});

describe("snap — source builders", () => {
  it("overlayEdgeSnapPoints yields start+end per overlay, excludes by id", () => {
    const subs = [
      { id: "a", text: "", startMs: 0, endMs: 1000, style: {} as any },
      { id: "b", text: "", startMs: 1500, endMs: 2000, style: {} as any },
    ];
    const all = overlayEdgeSnapPoints(subs);
    expect(all).toHaveLength(4);
    const excluded = overlayEdgeSnapPoints(subs, { excludeId: "a" });
    expect(excluded.every((p) => p.sourceId !== "a")).toBe(true);
    expect(excluded).toHaveLength(2);
  });

  it("subtitleEdgeSnapPoints excludes by index", () => {
    const subs = [
      { id: "a", text: "", startMs: 0, endMs: 1000, style: {} as any },
      { id: "b", text: "", startMs: 1500, endMs: 2000, style: {} as any },
    ];
    const r = subtitleEdgeSnapPoints(subs, { excludeSubtitleIndex: 0 });
    expect(r).toHaveLength(2);
    expect(r.every((p) => p.sourceId === "b")).toBe(true);
  });

  it("clipEdgeSnapPoints folds timelineStart + trimmed duration into edges", () => {
    const clips = [
      {
        id: "c1",
        timelineStartMs: 0,
        trimStartMs: 100,
        trimEndMs: 1100,
      } as any,
      {
        id: "c2",
        timelineStartMs: 1000,
        trimStartMs: 0,
        trimEndMs: 500,
      } as any,
    ];
    const r = clipEdgeSnapPoints(clips);
    expect(r.map((p) => p.ms).sort((a, b) => a - b)).toEqual([0, 1000, 1000, 1500]);
  });

  it("playhead + boundary sources", () => {
    expect(playheadSnapPoint(2_345).ms).toBe(2_345);
    const b = boundarySnapPoints(10_000);
    expect(b.map((p) => p.ms)).toEqual([0, 10_000]);
    expect(b.every((p) => p.kind === "boundary")).toBe(true);
  });
});
