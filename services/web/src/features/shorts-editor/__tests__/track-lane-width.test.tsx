/**
 * B12 wiring tests (2026-05-26): SubtitleTrack + ClipTrack route their
 * lane-background width through ``computeTrackLaneWidth(totalDurationMs,
 * zoom, containerWidthPx)`` so the lane paints across the full ruler
 * extent on short clips. The pure helper itself is covered in
 * timeline-math.test; this file covers the WIRING — i.e. that the
 * containerWidthPx prop actually drives the inline width style of the
 * lane element.
 */

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";

import { SubtitleTrack } from "../components/SubtitleTrack";
import { ClipTrack } from "../components/ClipTrack";

const NOOP = () => {};

describe("SubtitleTrack — lane width wiring (B12)", () => {
  it("clamps lane background to containerWidthPx when content is shorter", () => {
    const { getByTestId } = render(
      <SubtitleTrack
        subtitles={[]}
        zoom={100} // 100 px/sec
        totalDurationMs={5_000} // → 500 px content extent
        playheadMs={0}
        selectedSubtitleIndex={null}
        onSelectSubtitle={NOOP}
        onUpdateSubtitle={NOOP}
        onAddSubtitle={NOOP}
        containerWidthPx={1300}
      />,
    );
    const lane = getByTestId("subtitle-lane") as HTMLElement;
    // computeTrackLaneWidth(5000, 100, 1300) === 1300
    expect(lane.style.width).toBe("1300px");
  });

  it("falls back to the content extent when containerWidthPx is unset", () => {
    const { getByTestId } = render(
      <SubtitleTrack
        subtitles={[]}
        zoom={100}
        totalDurationMs={5_000}
        playheadMs={0}
        selectedSubtitleIndex={null}
        onSelectSubtitle={NOOP}
        onUpdateSubtitle={NOOP}
        onAddSubtitle={NOOP}
      />,
    );
    const lane = getByTestId("subtitle-lane") as HTMLElement;
    expect(lane.style.width).toBe("500px");
  });
});

describe("ClipTrack — lane width wiring (B12)", () => {
  it("clamps lane background to containerWidthPx when content is shorter", () => {
    const { getByTestId } = render(
      <ClipTrack
        clips={[]}
        zoom={100}
        selectedClipIndex={null}
        totalDurationMs={5_000} // 500 px content
        playheadMs={0}
        onSelectClip={NOOP}
        onTrimClip={NOOP}
        onSeek={NOOP}
        containerWidthPx={1300}
      />,
    );
    const lane = getByTestId("clip-lane") as HTMLElement;
    expect(lane.style.width).toBe("1300px");
  });

  it("uses content extent when no containerWidthPx is provided", () => {
    const { getByTestId } = render(
      <ClipTrack
        clips={[]}
        zoom={100}
        selectedClipIndex={null}
        totalDurationMs={5_000}
        playheadMs={0}
        onSelectClip={NOOP}
        onTrimClip={NOOP}
        onSeek={NOOP}
      />,
    );
    const lane = getByTestId("clip-lane") as HTMLElement;
    expect(lane.style.width).toBe("500px");
  });
});
