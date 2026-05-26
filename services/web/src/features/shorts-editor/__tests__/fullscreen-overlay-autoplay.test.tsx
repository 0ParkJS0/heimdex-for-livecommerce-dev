/**
 * B9 wiring test (2026-05-26): the fullscreen modal's host ``<video>``
 * must carry ``muted`` + ``preload="auto"`` + ``autoPlay`` so the
 * browser commits a first-frame paint on mount instead of sitting at
 * ``buffered=0`` black until the editor's pause useEffect lands.
 *
 * Cheaper than reproducing the actual black-frame symptom in jsdom —
 * we only assert the attributes are present on the rendered element.
 * Their *combination* (muted + preload + autoPlay) is the fix; if any
 * of the three is dropped this test fails.
 */

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";

import { FullscreenOverlay } from "../components/FullscreenOverlay";
import type { Playback } from "../lib/types";

const NOOP = () => {};
const IDLE: Playback = { kind: "idle" };

describe("FullscreenOverlay — autoPlay wiring (B9)", () => {
  it("host video has muted + preload=auto + autoPlay", () => {
    const { baseElement } = render(
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
    // FullscreenOverlay portals into document.body, so we look at
    // baseElement (document.body) rather than the wrapper container.
    // The first <video> is the host preview; the second (``hidden``)
    // is the preloadRef stub we deliberately ignore.
    const videos = baseElement.querySelectorAll("video");
    expect(videos.length).toBeGreaterThan(0);
    const hostVideo = videos[0] as HTMLVideoElement;
    expect(hostVideo.muted).toBe(true);
    expect(hostVideo.preload).toBe("auto");
    // ``autoplay`` reflects via both the attribute and the property —
    // assert both so a partial drop (attribute removed but property
    // somehow kept, or vice versa) still trips the test.
    expect(hostVideo.autoplay).toBe(true);
    expect(hostVideo.hasAttribute("autoplay")).toBe(true);
  });
});
