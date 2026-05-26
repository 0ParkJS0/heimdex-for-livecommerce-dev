/**
 * FullscreenOverlay — volume toggle (figma feedback 2026-05-26).
 *
 * The modal opens muted (autoplay-policy guard) and the transport row
 * exposes a toggle next to SkipForward. Pin the wiring so a future
 * refactor doesn't silently re-mute the element or drop the toggle —
 * the operator's complaint that surfaced this commit was "fullscreen
 * has no sound and no way to turn it on".
 */

import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";

import { FullscreenOverlay } from "../components/FullscreenOverlay";
import type { Playback } from "../lib/types";

const NOOP = () => {};
const IDLE: Playback = { kind: "idle" };

function renderOverlay() {
  return render(
    <FullscreenOverlay
      clips={[]}
      subtitles={[]}
      overlays={[]}
      playheadMs={0}
      playback={IDLE}
      totalDurationMs={0}
      selectedSubtitleIndex={null}
      onPlayheadChange={NOOP}
      dispatchPlaybackEvent={NOOP}
      onSelectSubtitle={NOOP}
      onUpdateSubtitlePosition={NOOP}
      onUpdateSubtitleFontSize={NOOP}
      onClose={NOOP}
    />,
  );
}

describe("FullscreenOverlay — volume toggle", () => {
  it("opens muted and the toggle button is in the unmute affordance", () => {
    const { baseElement } = renderOverlay();
    const host = baseElement.querySelector("video") as HTMLVideoElement;
    expect(host.muted).toBe(true);
    // When muted, the button offers to unmute.
    expect(baseElement.querySelector('[aria-label="음소거 해제"]')).toBeTruthy();
    expect(baseElement.querySelector('[aria-label="음소거"]')).toBeNull();
  });

  it("clicking the toggle unmutes the host video and flips the label", () => {
    const { baseElement } = renderOverlay();
    const host = baseElement.querySelector("video") as HTMLVideoElement;
    const unmuteBtn = baseElement.querySelector(
      '[aria-label="음소거 해제"]',
    ) as HTMLButtonElement;
    fireEvent.click(unmuteBtn);
    expect(host.muted).toBe(false);
    // After unmuting, the button offers to mute again.
    expect(baseElement.querySelector('[aria-label="음소거"]')).toBeTruthy();
    expect(baseElement.querySelector('[aria-label="음소거 해제"]')).toBeNull();
  });

  it("clicking the toggle again re-mutes the host video", () => {
    const { baseElement } = renderOverlay();
    const host = baseElement.querySelector("video") as HTMLVideoElement;
    fireEvent.click(
      baseElement.querySelector('[aria-label="음소거 해제"]') as HTMLButtonElement,
    );
    expect(host.muted).toBe(false);
    fireEvent.click(
      baseElement.querySelector('[aria-label="음소거"]') as HTMLButtonElement,
    );
    expect(host.muted).toBe(true);
  });
});
