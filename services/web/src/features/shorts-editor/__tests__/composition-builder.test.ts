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
    // 2026-05-26 — DEFAULT_OUTPUT.width restored to 406 (was 405).
    // contracts 0.18.0's strict validator rejects odd dimensions
    // (``libx264 requires even width/height``); the 0.13 % aspect
    // drift from the 9:16 ideal is invisible at integer-pixel
    // resolution.
    expect(spec.output.width).toBe(406);
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

    it("crops overlay timing ranges when inPoint/outPoint are set", () => {
      const state = makeState({
        clips: [clipA, clipB],
        totalDurationMs: 10000,
        inPointMs: 2000,
        outPointMs: 6000,
        overlays: [
          // fully before range — dropped
          {
            kind: "background" as const,
            id: "ov_before",
            startMs: 0,
            endMs: 1500,
            layerIndex: 0,
            transform: { x: 0.5, y: 0.5, rotationDeg: 0, widthPx: 100, heightPx: 100 },
            effects: { opacity: 1, stroke: null, shadow: null },
            fillColor: "#111",
            imageUrl: null,
          },
          // spans in-point — clamped
          {
            kind: "background" as const,
            id: "ov_spans_in",
            startMs: 1500,
            endMs: 3000,
            layerIndex: 1,
            transform: { x: 0.5, y: 0.5, rotationDeg: 0, widthPx: 100, heightPx: 100 },
            effects: { opacity: 1, stroke: null, shadow: null },
            fillColor: "#222",
            imageUrl: null,
          },
          // spans out-point — clamped
          {
            kind: "background" as const,
            id: "ov_spans_out",
            startMs: 5000,
            endMs: 8000,
            layerIndex: 2,
            transform: { x: 0.5, y: 0.5, rotationDeg: 0, widthPx: 100, heightPx: 100 },
            effects: { opacity: 1, stroke: null, shadow: null },
            fillColor: "#333",
            imageUrl: null,
          },
          // fully after range — dropped
          {
            kind: "background" as const,
            id: "ov_after",
            startMs: 7000,
            endMs: 9000,
            layerIndex: 3,
            transform: { x: 0.5, y: 0.5, rotationDeg: 0, widthPx: 100, heightPx: 100 },
            effects: { opacity: 1, stroke: null, shadow: null },
            fillColor: "#444",
            imageUrl: null,
          },
        ],
      });

      const spec = buildCompositionSpec(state);
      const ovIds = spec.overlays.map((o) => o.id);
      expect(ovIds).not.toContain("ov_before");
      expect(ovIds).not.toContain("ov_after");
      expect(ovIds).toContain("ov_spans_in");
      expect(ovIds).toContain("ov_spans_out");

      const spansIn = spec.overlays.find((o) => o.id === "ov_spans_in")!;
      // startMs clamped: max(0, 1500-2000) = 0; endMs: min(3000,6000)-2000 = 1000
      expect(spansIn.start_ms).toBe(0);
      expect(spansIn.end_ms).toBe(1000);

      const spansOut = spec.overlays.find((o) => o.id === "ov_spans_out")!;
      // startMs: max(0, 5000-2000) = 3000; endMs: min(8000,6000)-2000 = 4000
      expect(spansOut.start_ms).toBe(3000);
      expect(spansOut.end_ms).toBe(4000);
    });
  });

  // ---------------------------------------------------------------------------
  // PR #255 — video_transform, letterbox, layer_order serialization
  // ---------------------------------------------------------------------------

  describe("video_transform serialization", () => {
    it("emits video_transform with snake_case keys when rotationDeg != 0", () => {
      const state = makeState({
        videoTransform: {
          x: 0.5,
          y: 0.5,
          scale: 1,
          rotationDeg: 45,
          outline: null,
          shadow: null,
        },
      });
      const spec = buildCompositionSpec(state);
      expect(spec.video_transform).toBeDefined();
      expect(spec.video_transform!.rotation_deg).toBe(45);
    });

    it("emits video_transform with outline.width_px when outline present", () => {
      const state = makeState({
        videoTransform: {
          x: 0.5,
          y: 0.5,
          scale: 1,
          rotationDeg: 0,
          outline: { color: "#FF0000", widthPx: 8 },
          shadow: null,
        },
      });
      const spec = buildCompositionSpec(state);
      expect(spec.video_transform).toBeDefined();
      expect(spec.video_transform!.outline).not.toBeNull();
      expect(spec.video_transform!.outline!.width_px).toBe(8);
      expect(spec.video_transform!.outline!.color).toBe("#FF0000");
    });

    it("emits video_transform with shadow.blur_px when shadow present", () => {
      const state = makeState({
        videoTransform: {
          x: 0.5,
          y: 0.5,
          scale: 1,
          rotationDeg: 0,
          outline: null,
          shadow: {
            color: "#000000",
            offsetX: 5,
            offsetY: 10,
            blurPx: 15,
            spreadPx: 2,
          },
        },
      });
      const spec = buildCompositionSpec(state);
      expect(spec.video_transform).toBeDefined();
      const s = spec.video_transform!.shadow!;
      expect(s.blur_px).toBe(15);
      expect(s.offset_x).toBe(5);
      expect(s.offset_y).toBe(10);
      expect(s.spread_px).toBe(2);
      expect(s.color).toBe("#000000");
    });

    it("omits video_transform when all defaults (x=0.5, y=0.5, scale=1, rotationDeg=0, no outline, no shadow)", () => {
      const state = makeState({
        videoTransform: {
          x: 0.5,
          y: 0.5,
          scale: 1,
          rotationDeg: 0,
          outline: null,
          shadow: null,
        },
      });
      const spec = buildCompositionSpec(state);
      expect(spec.video_transform).toBeUndefined();
    });

    it("omits video_transform when outline is present but widthPx is 0 (treated as no-outline)", () => {
      // widthPx=0 means the operator cleared it but didn't null it — builder
      // treats hasOutline = widthPx > 0, so this is still default.
      const state = makeState({
        videoTransform: {
          x: 0.5,
          y: 0.5,
          scale: 1,
          rotationDeg: 0,
          outline: { color: "#FF0000", widthPx: 0 },
          shadow: null,
        },
      });
      const spec = buildCompositionSpec(state);
      expect(spec.video_transform).toBeUndefined();
    });
  });

  describe("letterbox serialization", () => {
    it("serializes letterbox to snake_case fields", () => {
      const state = makeState({
        letterbox: {
          topHeightPct: 12,
          bottomHeightPct: 8,
          fillColor: "#111111",
          borderColor: "#FF0000",
          borderWidthPx: 3,
        },
      });
      const spec = buildCompositionSpec(state);
      expect(spec.letterbox).toBeDefined();
      expect(spec.letterbox!.top_height_pct).toBe(12);
      expect(spec.letterbox!.bottom_height_pct).toBe(8);
      expect(spec.letterbox!.fill_color).toBe("#111111");
      expect(spec.letterbox!.border_color).toBe("#FF0000");
      expect(spec.letterbox!.border_width_px).toBe(3);
    });

    it("omits letterbox when state.letterbox is undefined", () => {
      const state = makeState({ letterbox: undefined });
      const spec = buildCompositionSpec(state);
      expect(spec.letterbox).toBeUndefined();
    });

    it("serializes letterbox with null border_color when borderColor is null", () => {
      const state = makeState({
        letterbox: {
          topHeightPct: 10,
          bottomHeightPct: 10,
          fillColor: "#000000",
          borderColor: null,
          borderWidthPx: 0,
        },
      });
      const spec = buildCompositionSpec(state);
      expect(spec.letterbox!.border_color).toBeNull();
    });
  });

  describe("layer_order serialization", () => {
    it("preserves overlay ids in layer_order with kind='overlay'", () => {
      const state = makeState({
        layerOrder: [
          { kind: "video" as const },
          { kind: "letterbox" as const },
          { kind: "subtitles" as const },
          { kind: "overlay" as const, id: "ov_abc123" },
          { kind: "overlay" as const, id: "ov_def456" },
        ],
      });
      const spec = buildCompositionSpec(state);
      expect(spec.layer_order).toBeDefined();
      const overlayEntries = spec.layer_order!.filter((l) => l.kind === "overlay");
      expect(overlayEntries).toHaveLength(2);
      expect(overlayEntries[0].id).toBe("ov_abc123");
      expect(overlayEntries[1].id).toBe("ov_def456");
    });

    it("non-overlay entries have no id field", () => {
      const state = makeState({
        layerOrder: [
          { kind: "video" as const },
          { kind: "subtitles" as const },
        ],
      });
      const spec = buildCompositionSpec(state);
      for (const entry of spec.layer_order!) {
        if (entry.kind !== "overlay") {
          expect(entry.id).toBeUndefined();
        }
      }
    });

    it("preserves order of all layer kinds", () => {
      const state = makeState({
        layerOrder: [
          { kind: "video" as const },
          { kind: "letterbox" as const },
          { kind: "subtitles" as const },
          { kind: "overlay" as const, id: "ov_1" },
        ],
      });
      const spec = buildCompositionSpec(state);
      expect(spec.layer_order!.map((l) => l.kind)).toEqual([
        "video",
        "letterbox",
        "subtitles",
        "overlay",
      ]);
    });
  });
});
