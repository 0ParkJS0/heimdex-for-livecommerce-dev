import { describe, it, expect } from "vitest";
import { buildCompositionSpec } from "../lib/composition-builder";
import type { EditorState } from "../lib/types";
import { DEFAULT_SUBTITLE_STYLE } from "../constants";

function makeState(overrides: Partial<EditorState> = {}): EditorState {
  return {
    videoId: "gd_test",
    sourceType: "gdrive",
    clips: [],
    subtitles: [],
    overlays: [],
    videoTransform: {
      x: 0.5,
      y: 0.5,
      scale: 1,
      rotationDeg: 0,
      outline: null,
      shadow: null,
    },
    layerOrder: [{ kind: "video" }, { kind: "subtitles" }],
    selectedClipIndex: null,
    selectedSubtitleIndex: null,
    selectedOverlayId: null,
    selectedVideo: false,
    selectedLetterbox: false,
    razorMode: false,
    playheadMs: 0,
    playback: { kind: "idle" },
    totalDurationMs: 0,
    zoom: 100,
    isDirty: false,
    history: [],
    redoHistory: [],
    inPointMs: null,
    outPointMs: null,
    ...overrides,
  };
}

describe("buildCompositionSpec", () => {
  it("builds valid spec from single clip", () => {
    const state = makeState({
      clips: [
        {
          id: "c1",
          sceneId: "scene_1",
          videoId: "gd_v1",
          sourceType: "gdrive",
          originalStartMs: 0,
          originalEndMs: 5000,
          trimStartMs: 1000,
          trimEndMs: 4000,
          timelineStartMs: 0,
          volume: 1.5,
        },
      ],
      totalDurationMs: 3000,
    });

    const spec = buildCompositionSpec(state, "My Short");

    expect(spec.version).toBe(1);
    expect(spec.title).toBe("My Short");
    // 2026-05-19 — DEFAULT_OUTPUT.width was nudged from 406 → 405 so
    // the output frame is exact 9:16 (matches FullscreenOverlay +
    // EditorLayout preview slot).
    expect(spec.output.width).toBe(405);
    expect(spec.output.height).toBe(720);
    expect(spec.output.fps).toBe(30);
    expect(spec.scene_clips).toHaveLength(1);
    expect(spec.scene_clips[0].scene_id).toBe("scene_1");
    expect(spec.scene_clips[0].start_ms).toBe(1000);
    expect(spec.scene_clips[0].end_ms).toBe(4000);
    expect(spec.scene_clips[0].timeline_start_ms).toBe(0);
    expect(spec.scene_clips[0].volume).toBe(1.5);
    expect(spec.scene_clips[0].crop_w).toBe(1.0);
    expect(spec.subtitles).toHaveLength(0);
    expect(spec.transitions).toHaveLength(0);
  });

  it("builds spec with multiple clips and subtitles", () => {
    const state = makeState({
      clips: [
        {
          id: "c1",
          sceneId: "s1",
          videoId: "v1",
          sourceType: "gdrive",
          originalStartMs: 0,
          originalEndMs: 3000,
          trimStartMs: 0,
          trimEndMs: 3000,
          timelineStartMs: 0,
          volume: 1.0,
        },
        {
          id: "c2",
          sceneId: "s2",
          videoId: "v1",
          sourceType: "gdrive",
          originalStartMs: 5000,
          originalEndMs: 8000,
          trimStartMs: 5000,
          trimEndMs: 8000,
          timelineStartMs: 3000,
          volume: 0.8,
        },
      ],
      subtitles: [
        {
          id: "sub1",
          text: "Hello World",
          startMs: 0,
          endMs: 2000,
          style: { ...DEFAULT_SUBTITLE_STYLE },
        },
      ],
      totalDurationMs: 6000,
    });

    const spec = buildCompositionSpec(state);

    expect(spec.scene_clips).toHaveLength(2);
    expect(spec.scene_clips[1].timeline_start_ms).toBe(3000);
    expect(spec.scene_clips[1].volume).toBe(0.8);
    expect(spec.subtitles).toHaveLength(1);
    expect(spec.subtitles[0].text).toBe("Hello World");
    expect(spec.subtitles[0].style.font_family).toBe("Pretendard");
    // 2026-05-22 — DEFAULT_SUBTITLE_STYLE.fontSizePx bumped to 29
    // (PR 10 / Item 11 / D11=A) so the editor's manual-add subtitle
    // reads as ~25 px in the 352×626 preview reference (29 ×
    // 626/720 ≈ 25.2). Stored value stays in 720-tall output coords
    // for backend renderer compatibility; the editor preview scales
    // down via container queries. AI-shorts captions still come
    // through build_auto_shorts_subtitle_style at 32 px so this
    // constant remains decoupled from that path.
    expect(spec.subtitles[0].style.font_size_px).toBe(29);
    expect(spec.subtitles[0].style.position_y).toBe(0.8);
    expect(spec.title).toBeNull();
  });

  it("builds empty spec with no clips", () => {
    const state = makeState();
    const spec = buildCompositionSpec(state);

    expect(spec.scene_clips).toHaveLength(0);
    expect(spec.subtitles).toHaveLength(0);
  });

  it("maps subtitle style fields to snake_case", () => {
    const state = makeState({
      clips: [
        {
          id: "c1",
          sceneId: "s1",
          videoId: "v1",
          sourceType: "gdrive",
          originalStartMs: 0,
          originalEndMs: 5000,
          trimStartMs: 0,
          trimEndMs: 5000,
          timelineStartMs: 0,
          volume: 1.0,
        },
      ],
      subtitles: [
        {
          id: "sub1",
          text: "Test",
          startMs: 0,
          endMs: 1000,
          style: {
            fontFamily: "Noto Sans KR",
            fontSizePx: 48,
            fontColor: "#FF0000",
            fontWeight: 400,
            positionX: 0.3,
            positionY: 0.7,
            backgroundColor: "#000000",
            backgroundOpacity: 0.8,
          },
        },
      ],
    });

    const spec = buildCompositionSpec(state);
    const style = spec.subtitles[0].style;

    expect(style.font_family).toBe("Noto Sans KR");
    expect(style.font_size_px).toBe(48);
    expect(style.font_color).toBe("#FF0000");
    expect(style.font_weight).toBe(400);
    expect(style.position_x).toBe(0.3);
    expect(style.position_y).toBe(0.7);
    expect(style.background_color).toBe("#000000");
    expect(style.background_opacity).toBe(0.8);
  });

  // L4 / T2 — export range cropping.
  describe("inPoint/outPoint cropping", () => {
    const clipA = {
      id: "ca",
      sceneId: "sa",
      videoId: "v",
      sourceType: "gdrive",
      originalStartMs: 0,
      originalEndMs: 4000,
      trimStartMs: 0,
      trimEndMs: 4000,
      timelineStartMs: 0,
      volume: 1.0,
    };
    const clipB = {
      id: "cb",
      sceneId: "sb",
      videoId: "v",
      sourceType: "gdrive",
      originalStartMs: 0,
      originalEndMs: 6000,
      trimStartMs: 0,
      trimEndMs: 6000,
      timelineStartMs: 4000,
      volume: 1.0,
    };

    it("drops clips entirely outside the range and trims partial ones", () => {
      const state = makeState({
        clips: [clipA, clipB],
        totalDurationMs: 10000,
        inPointMs: 3000,
        outPointMs: 7000,
      });
      const spec = buildCompositionSpec(state);
      // Both clips overlap the range.
      expect(spec.scene_clips).toHaveLength(2);
      // clipA: timelineStart shifts from 0 to 0 (3000 - 3000), trimStart
      // advances by 3000 so source frames before t=3000 are skipped.
      expect(spec.scene_clips[0].timeline_start_ms).toBe(0);
      expect(spec.scene_clips[0].start_ms).toBe(3000);
      expect(spec.scene_clips[0].end_ms).toBe(4000);
      // clipB: timelineStart shifts from 4000 → 1000 (4000 - 3000),
      // trimEnd reduced by (clipEnd 10000 - outPoint 7000) = 3000.
      expect(spec.scene_clips[1].timeline_start_ms).toBe(1000);
      expect(spec.scene_clips[1].start_ms).toBe(0);
      expect(spec.scene_clips[1].end_ms).toBe(3000);
    });

    it("clamps subtitle start/end to the range", () => {
      const state = makeState({
        clips: [clipA, clipB],
        totalDurationMs: 10000,
        inPointMs: 2000,
        outPointMs: 5000,
        subtitles: [
          { id: "s1", text: "before", startMs: 0, endMs: 1500, style: { ...DEFAULT_SUBTITLE_STYLE } },
          { id: "s2", text: "spans-in", startMs: 1800, endMs: 3000, style: { ...DEFAULT_SUBTITLE_STYLE } },
          { id: "s3", text: "spans-out", startMs: 4000, endMs: 6000, style: { ...DEFAULT_SUBTITLE_STYLE } },
          { id: "s4", text: "after", startMs: 5500, endMs: 6500, style: { ...DEFAULT_SUBTITLE_STYLE } },
        ],
      });
      const spec = buildCompositionSpec(state);
      // s1 (before range) and s4 (after range) dropped.
      expect(spec.subtitles.map((s) => s.text)).toEqual(["spans-in", "spans-out"]);
      // s2 clamped: starts at 0 (1800 - 2000 → clamped to 0), ends at 1000.
      expect(spec.subtitles[0].start_ms).toBe(0);
      expect(spec.subtitles[0].end_ms).toBe(1000);
      // s3 clamped: starts at 2000, ends at 3000 (5000 outPoint - 2000 in).
      expect(spec.subtitles[1].start_ms).toBe(2000);
      expect(spec.subtitles[1].end_ms).toBe(3000);
    });

    it("no-ops when neither inPointMs nor outPointMs is set", () => {
      const state = makeState({
        clips: [clipA, clipB],
        totalDurationMs: 10000,
      });
      const spec = buildCompositionSpec(state);
      expect(spec.scene_clips).toHaveLength(2);
      expect(spec.scene_clips[0].timeline_start_ms).toBe(0);
      expect(spec.scene_clips[1].timeline_start_ms).toBe(4000);
    });
  });
});
