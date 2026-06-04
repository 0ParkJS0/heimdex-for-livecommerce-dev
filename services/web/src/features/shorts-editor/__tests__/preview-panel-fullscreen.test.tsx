/**
 * PreviewPanel fullscreen wiring (2026-05-26).
 *
 * Pins the scale-up refactor: the same PreviewPanel instance flips
 * its outer wrapper to ``fixed inset-0`` instead of being unmounted
 * and replaced by a separate FullscreenOverlay component. The
 * operator-reported "fullscreen has no image and no sound" symptom
 * was a direct consequence of mounting a second <video> element
 * whose ``src`` was set asynchronously by usePlaybackSync's useEffect
 * — the new element could race the hydration of ``state.clips`` and
 * end up with ``video.src=""`` permanently. Keeping a single video
 * element across the toggle means src/currentTime/audio state are
 * preserved by construction.
 *
 * These fixtures cover:
 *   * close chrome is only present when fullscreen=true
 *   * filename surfaces in fullscreen
 *   * clicking the close button calls onCloseFullscreen
 *   * ESC keydown while fullscreen=true calls onCloseFullscreen
 *   * the <video> element survives the fullscreen toggle (same
 *     DOM node identity before and after) — the actual src-race
 *     defence
 */

import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";

import { PreviewPanel } from "../components/PreviewPanel";
import type { EditorClip, Playback, PlaybackEvent } from "../lib/types";

const NOOP = () => {};
const IDLE: Playback = { kind: "idle" };
const CLIP: EditorClip = {
  id: "clip-1",
  sceneId: "scene-1",
  videoId: "video-1",
  sourceType: "drive",
  originalStartMs: 0,
  originalEndMs: 10_000,
  trimStartMs: 0,
  trimEndMs: 10_000,
  timelineStartMs: 0,
  volume: 1,
};

interface RenderOptions {
  fullscreen?: boolean;
  onCloseFullscreen?: () => void;
  filename?: string;
  onClearSelections?: () => void;
  onPlayheadChange?: (ms: number) => void;
  dispatchPlaybackEvent?: (event: PlaybackEvent) => void;
  totalDurationMs?: number;
  clips?: EditorClip[];
}

function renderPanel(opts: RenderOptions = {}) {
  return render(
    <PreviewPanel
      clips={opts.clips ?? []}
      subtitles={[]}
      playheadMs={0}
      playback={IDLE}
      totalDurationMs={opts.totalDurationMs ?? 0}
      selectedSubtitleIndex={null}
      onPlayheadChange={opts.onPlayheadChange ?? NOOP}
      dispatchPlaybackEvent={opts.dispatchPlaybackEvent ?? NOOP}
      onSelectSubtitle={NOOP}
      onUpdateSubtitlePosition={NOOP}
      onUpdateSubtitleFontSize={NOOP}
      onClearSelections={opts.onClearSelections}
      fullscreen={opts.fullscreen}
      onCloseFullscreen={opts.onCloseFullscreen}
      filename={opts.filename}
    />,
  );
}

describe("PreviewPanel — fullscreen chrome", () => {
  it("hides the close button + filename when fullscreen is false", () => {
    const { queryByTestId } = renderPanel({
      fullscreen: false,
      filename: "short.mp4",
    });
    expect(queryByTestId("preview-fullscreen-close")).toBeNull();
    expect(queryByTestId("preview-fullscreen-filename")).toBeNull();
  });

  it("renders the close button when fullscreen is true", () => {
    const { getByTestId } = renderPanel({
      fullscreen: true,
      onCloseFullscreen: NOOP,
    });
    expect(getByTestId("preview-fullscreen-close")).toBeTruthy();
  });

  it("surfaces the filename in fullscreen", () => {
    const { getByTestId } = renderPanel({
      fullscreen: true,
      onCloseFullscreen: NOOP,
      filename: "260309 종가 영상.mp4",
    });
    const label = getByTestId("preview-fullscreen-filename");
    expect(label.textContent).toBe("260309 종가 영상.mp4");
  });

  it("clicking the close button calls onCloseFullscreen exactly once", () => {
    const onClose = vi.fn();
    const { getByTestId } = renderPanel({
      fullscreen: true,
      onCloseFullscreen: onClose,
    });
    fireEvent.click(getByTestId("preview-fullscreen-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ESC keydown while fullscreen calls onCloseFullscreen", () => {
    const onClose = vi.fn();
    renderPanel({ fullscreen: true, onCloseFullscreen: onClose });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ESC keydown does NOT fire onCloseFullscreen when fullscreen is false", () => {
    const onClose = vi.fn();
    renderPanel({ fullscreen: false, onCloseFullscreen: onClose });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("lets fullscreen canvas clicks pass through transport chrome to clear selections", () => {
    const onClearSelections = vi.fn();
    const { getByTestId } = renderPanel({
      fullscreen: true,
      onCloseFullscreen: NOOP,
      onClearSelections,
    });

    fireEvent.click(getByTestId("preview-canvas"));

    expect(onClearSelections).toHaveBeenCalledTimes(1);
  });

  it("keeps fullscreen transport control clicks from clearing selections", () => {
    const onClearSelections = vi.fn();
    const dispatchPlaybackEvent = vi.fn();
    const { getByRole } = renderPanel({
      fullscreen: true,
      onCloseFullscreen: NOOP,
      onClearSelections,
      dispatchPlaybackEvent,
      clips: [CLIP],
    });

    fireEvent.click(getByRole("button", { name: "재생" }));

    expect(dispatchPlaybackEvent).toHaveBeenCalledWith({ kind: "TOGGLE" });
    expect(onClearSelections).not.toHaveBeenCalled();
  });

  it("seeks from the fullscreen progress control without clearing selections", () => {
    const onClearSelections = vi.fn();
    const onPlayheadChange = vi.fn();
    const { getByRole } = renderPanel({
      fullscreen: true,
      onCloseFullscreen: NOOP,
      onClearSelections,
      onPlayheadChange,
      totalDurationMs: 100_000,
    });
    const progress = getByRole("slider", { name: "재생 진행" });
    progress.getBoundingClientRect = () =>
      ({
        left: 0,
        width: 200,
        top: 0,
        bottom: 4,
        right: 200,
        height: 4,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect;

    fireEvent.click(progress, { clientX: 50 });

    expect(onPlayheadChange).toHaveBeenCalledWith(25_000);
    expect(onClearSelections).not.toHaveBeenCalled();
  });
});

describe("PreviewPanel — video element survives fullscreen toggle", () => {
  it("keeps the same <video> DOM node when fullscreen flips false → true → false", () => {
    // This is the root-cause defence: the old FullscreenOverlay
    // mounted a second <video> whose src had to race usePlaybackSync's
    // useEffect. Scaling up the same PreviewPanel instance means the
    // video node identity is preserved across the toggle, so
    // src/currentTime/muted state can't be lost mid-transition.
    const { baseElement, rerender } = render(
      <PreviewPanel
        clips={[]}
        subtitles={[]}
        playheadMs={0}
        playback={IDLE}
        totalDurationMs={0}
        selectedSubtitleIndex={null}
        onPlayheadChange={NOOP}
        dispatchPlaybackEvent={NOOP}
        onSelectSubtitle={NOOP}
        onUpdateSubtitlePosition={NOOP}
        onUpdateSubtitleFontSize={NOOP}
        fullscreen={false}
      />,
    );
    const videoBefore = baseElement.querySelector("video");
    // The PreviewPanel mount-time render always paints the host
    // <video> element even with an empty clips list, so identity
    // before the toggle is well defined.
    expect(videoBefore).toBeTruthy();

    rerender(
      <PreviewPanel
        clips={[]}
        subtitles={[]}
        playheadMs={0}
        playback={IDLE}
        totalDurationMs={0}
        selectedSubtitleIndex={null}
        onPlayheadChange={NOOP}
        dispatchPlaybackEvent={NOOP}
        onSelectSubtitle={NOOP}
        onUpdateSubtitlePosition={NOOP}
        onUpdateSubtitleFontSize={NOOP}
        fullscreen
        onCloseFullscreen={NOOP}
      />,
    );
    const videoAfterEnter = baseElement.querySelector("video");
    expect(videoAfterEnter).toBe(videoBefore);

    rerender(
      <PreviewPanel
        clips={[]}
        subtitles={[]}
        playheadMs={0}
        playback={IDLE}
        totalDurationMs={0}
        selectedSubtitleIndex={null}
        onPlayheadChange={NOOP}
        dispatchPlaybackEvent={NOOP}
        onSelectSubtitle={NOOP}
        onUpdateSubtitlePosition={NOOP}
        onUpdateSubtitleFontSize={NOOP}
        fullscreen={false}
      />,
    );
    const videoAfterExit = baseElement.querySelector("video");
    expect(videoAfterExit).toBe(videoBefore);
  });
});
