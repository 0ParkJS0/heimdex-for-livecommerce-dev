import { act, render } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePlaybackSync } from "../hooks/usePlaybackSync";
import { recomputeTimeline } from "../lib/timeline-math";
import type { EditorClip, PlaybackEvent } from "../lib/types";

function makeClip(
  trimStart: number,
  trimEnd: number,
  videoId: string,
  id: string,
): EditorClip {
  return {
    id,
    sceneId: id,
    videoId,
    sourceType: "gdrive",
    originalStartMs: trimStart,
    originalEndMs: trimEnd,
    trimStartMs: trimStart,
    trimEndMs: trimEnd,
    timelineStartMs: 0,
    volume: 1,
  };
}

function PlaybackHarness({
  clips,
  initialPlayheadMs,
  onEvent,
}: {
  clips: EditorClip[];
  initialPlayheadMs: number;
  onEvent: (event: PlaybackEvent) => void;
}) {
  const [playheadMs, setPlayheadMs] = useState(initialPlayheadMs);
  const { videoRef, preloadRef, onSeeked, onEnded } = usePlaybackSync({
    clips,
    playheadMs,
    playback: { kind: "playing", rate: 1 },
    onPlayheadChange: setPlayheadMs,
    dispatchPlaybackEvent: onEvent,
  });

  return (
    <>
      <video ref={videoRef} onSeeked={onSeeked} onEnded={onEnded} />
      <video ref={preloadRef} />
      <span data-testid="playhead">{playheadMs}</span>
    </>
  );
}

describe("usePlaybackSync timeline loop", () => {
  let now = 0;
  let rafCallbacks: FrameRequestCallback[] = [];
  let playSpy: ReturnType<typeof vi.spyOn>;
  let loadSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    now = 0;
    rafCallbacks = [];
    vi.spyOn(performance, "now").mockImplementation(() => now);
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      rafCallbacks.push(cb);
      return rafCallbacks.length;
    });
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    playSpy = vi
      .spyOn(HTMLMediaElement.prototype, "play")
      .mockResolvedValue(undefined);
    loadSpy = vi
      .spyOn(HTMLMediaElement.prototype, "load")
      .mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("resumes the media element after looping across different source videos", async () => {
    const clips = recomputeTimeline([
      makeClip(0, 1000, "first-video", "clip-1"),
      makeClip(0, 1000, "second-video", "clip-2"),
    ]);

    const onEvent = vi.fn();
    const { getByTestId } = render(
      <PlaybackHarness
        clips={clips}
        initialPlayheadMs={1000}
        onEvent={onEvent}
      />,
    );

    expect(playSpy).toHaveBeenCalledTimes(1);
    expect(loadSpy).toHaveBeenCalled();
    expect(rafCallbacks.length).toBeGreaterThan(0);

    now = 1001;
    await act(async () => {
      rafCallbacks[0](now);
    });

    expect(getByTestId("playhead").textContent).toBe("0");
    expect(playSpy).toHaveBeenCalledTimes(2);
    expect(onEvent).not.toHaveBeenCalledWith({ kind: "REACHED_END" });
  });
});
