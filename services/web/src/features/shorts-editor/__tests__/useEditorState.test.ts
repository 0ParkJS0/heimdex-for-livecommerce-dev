import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useEditorState, createClipFromScene } from "../hooks/useEditorState";
import type { EditorClip } from "../lib/types";

function makeClip(overrides: Partial<EditorClip> = {}): EditorClip {
  return {
    id: `clip_${Math.random()}`,
    sceneId: "scene_1",
    videoId: "gd_video1",
    sourceType: "gdrive",
    originalStartMs: 0,
    originalEndMs: 5000,
    trimStartMs: 0,
    trimEndMs: 5000,
    timelineStartMs: 0,
    volume: 1.0,
    ...overrides,
  };
}

describe("useEditorState", () => {
  it("initializes with empty state", () => {
    const { result } = renderHook(() => useEditorState());
    expect(result.current.state.clips).toHaveLength(0);
    expect(result.current.state.isDirty).toBe(false);
  });

  it("INIT_FROM_SCENES sets clips and computes timeline", () => {
    const { result } = renderHook(() => useEditorState());
    const clip1 = makeClip({ id: "c1", originalStartMs: 0, originalEndMs: 3000, trimStartMs: 0, trimEndMs: 3000 });
    const clip2 = makeClip({ id: "c2", originalStartMs: 10000, originalEndMs: 15000, trimStartMs: 10000, trimEndMs: 15000 });

    act(() => result.current.initFromScenes("vid1", "gdrive", [clip1, clip2]));

    expect(result.current.state.clips).toHaveLength(2);
    expect(result.current.state.clips[0].timelineStartMs).toBe(0);
    expect(result.current.state.clips[1].timelineStartMs).toBe(3000);
    expect(result.current.state.totalDurationMs).toBe(8000);
    expect(result.current.state.videoId).toBe("vid1");
    expect(result.current.state.isDirty).toBe(false);
  });

  it("ADD_CLIP appends and recomputes timeline", () => {
    const { result } = renderHook(() => useEditorState());
    const clip1 = makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 2000 });

    act(() => result.current.initFromScenes("v", "gdrive", [clip1]));
    act(() => result.current.addClip(makeClip({ id: "c2", trimStartMs: 5000, trimEndMs: 8000 })));

    expect(result.current.state.clips).toHaveLength(2);
    expect(result.current.state.clips[1].timelineStartMs).toBe(2000);
    expect(result.current.state.totalDurationMs).toBe(5000);
    expect(result.current.state.isDirty).toBe(true);
  });

  it("REMOVE_CLIP removes without recomputing positions", () => {
    const { result } = renderHook(() => useEditorState());
    const clips = [
      makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 2000 }),
      makeClip({ id: "c2", trimStartMs: 0, trimEndMs: 3000 }),
    ];

    act(() => result.current.initFromScenes("v", "gdrive", clips));
    act(() => result.current.removeClip(0));

    expect(result.current.state.clips).toHaveLength(1);
    expect(result.current.state.clips[0].id).toBe("c2");
    // Gaps allowed — clip keeps its original timelineStartMs (2000)
    expect(result.current.state.clips[0].timelineStartMs).toBe(2000);
    expect(result.current.state.totalDurationMs).toBe(5000);
  });

  it("REMOVE_CLIP adjusts selectedClipIndex when removing before selected", () => {
    const { result } = renderHook(() => useEditorState());
    const clips = [
      makeClip({ id: "a", trimStartMs: 0, trimEndMs: 1000 }),
      makeClip({ id: "b", trimStartMs: 0, trimEndMs: 2000 }),
      makeClip({ id: "c", trimStartMs: 0, trimEndMs: 3000 }),
    ];
    act(() => result.current.initFromScenes("v", "gdrive", clips));
    act(() => result.current.selectClip(2)); // select "c"
    act(() => result.current.removeClip(0)); // remove "a"

    // "c" was at index 2, now should be at index 1
    expect(result.current.state.selectedClipIndex).toBe(1);
    expect(result.current.state.clips[1].id).toBe("c");
  });

  it("REMOVE_SUBTITLE adjusts selectedSubtitleIndex when removing before selected", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    const sub = (id: string) => ({
      id,
      text: id,
      startMs: 0,
      endMs: 1000,
      style: {
        fontFamily: "Pretendard",
        fontSizePx: 36,
        fontColor: "#FFFFFF",
        fontWeight: 700,
        positionX: 0.5,
        positionY: 0.85,
        backgroundColor: null,
        backgroundOpacity: 0.6,
      },
    });
    act(() => result.current.addSubtitle(sub("s1")));
    act(() => result.current.addSubtitle(sub("s2")));
    act(() => result.current.addSubtitle(sub("s3")));
    act(() => result.current.selectSubtitle(2)); // select "s3"
    act(() => result.current.removeSubtitle(0)); // remove "s1"

    expect(result.current.state.selectedSubtitleIndex).toBe(1);
    expect(result.current.state.subtitles[1].id).toBe("s3");
  });

  it("REMOVE_CLIP ignores out of range", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.removeClip(5));
    expect(result.current.state.clips).toHaveLength(1);
  });

  it("REORDER_CLIPS swaps array order without recomputing positions", () => {
    const { result } = renderHook(() => useEditorState());
    const clips = [
      makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 2000 }),
      makeClip({ id: "c2", trimStartMs: 0, trimEndMs: 5000 }),
    ];

    act(() => result.current.initFromScenes("v", "gdrive", clips));
    act(() => result.current.reorderClips(0, 1));

    // Array order swapped; positions preserved from initial layout.
    expect(result.current.state.clips[0].id).toBe("c2");
    expect(result.current.state.clips[1].id).toBe("c1");
    // Clips keep their timelineStartMs from the initial packed layout
    // (c2 was at 2000, c1 was at 0).
    expect(result.current.state.clips[0].timelineStartMs).toBe(2000);
    expect(result.current.state.clips[1].timelineStartMs).toBe(0);
    expect(result.current.state.selectedClipIndex).toBe(1);
  });

  it("REORDER_CLIPS ignores same index", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip({ id: "c1" })]));
    act(() => result.current.reorderClips(0, 0));
    expect(result.current.state.isDirty).toBe(false);
  });

  it("TRIM_CLIP clamps within scene bounds", () => {
    const { result } = renderHook(() => useEditorState());
    const clip = makeClip({
      id: "c1",
      originalStartMs: 1000,
      originalEndMs: 6000,
      trimStartMs: 1000,
      trimEndMs: 6000,
    });

    act(() => result.current.initFromScenes("v", "gdrive", [clip]));

    // Try to trim start before original start
    act(() => result.current.trimClip(0, 500, undefined));
    expect(result.current.state.clips[0].trimStartMs).toBe(1000);

    // Try to trim end past original end
    act(() => result.current.trimClip(0, undefined, 9000));
    expect(result.current.state.clips[0].trimEndMs).toBe(6000);

    // Valid trim — start trim shifts timelineStartMs forward
    act(() => result.current.trimClip(0, 2000, 4000));
    expect(result.current.state.clips[0].trimStartMs).toBe(2000);
    expect(result.current.state.clips[0].trimEndMs).toBe(4000);
    // timelineStartMs shifted by (2000-1000) = 1000, so clip starts at 1000
    // totalDurationMs = 1000 + (4000-2000) = 3000
    expect(result.current.state.clips[0].timelineStartMs).toBe(1000);
    expect(result.current.state.totalDurationMs).toBe(3000);
  });

  it("TRIM_CLIP ensures start < end", () => {
    const { result } = renderHook(() => useEditorState());
    const clip = makeClip({
      id: "c1",
      originalStartMs: 0,
      originalEndMs: 5000,
      trimStartMs: 0,
      trimEndMs: 5000,
    });

    act(() => result.current.initFromScenes("v", "gdrive", [clip]));
    // Try to set start past current end
    act(() => result.current.trimClip(0, 6000, undefined));
    expect(result.current.state.clips[0].trimStartMs).toBeLessThan(
      result.current.state.clips[0].trimEndMs,
    );
  });

  it("SET_CLIP_VOLUME clamps to 0-3", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip({ id: "c1" })]));

    act(() => result.current.setClipVolume(0, 5.0));
    expect(result.current.state.clips[0].volume).toBe(3);

    act(() => result.current.setClipVolume(0, -1));
    expect(result.current.state.clips[0].volume).toBe(0);

    act(() => result.current.setClipVolume(0, 1.5));
    expect(result.current.state.clips[0].volume).toBe(1.5);
  });

  it("SELECT_CLIP deselects subtitle", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.selectSubtitle(0));
    act(() => result.current.selectClip(0));
    expect(result.current.state.selectedClipIndex).toBe(0);
    expect(result.current.state.selectedSubtitleIndex).toBeNull();
  });

  it("subtitle CRUD works", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    const sub = {
      id: "sub1",
      text: "Hello",
      startMs: 0,
      endMs: 2000,
      style: {
        fontFamily: "Pretendard",
        fontSizePx: 36,
        fontColor: "#FFFFFF",
        fontWeight: 700,
        positionX: 0.5,
        positionY: 0.85,
        backgroundColor: null,
        backgroundOpacity: 0.6,
      },
    };

    act(() => result.current.addSubtitle(sub));
    expect(result.current.state.subtitles).toHaveLength(1);

    act(() => result.current.updateSubtitle(0, { text: "Updated" }));
    expect(result.current.state.subtitles[0].text).toBe("Updated");

    act(() => result.current.removeSubtitle(0));
    expect(result.current.state.subtitles).toHaveLength(0);
  });

  it("SET_ZOOM clamps to 0.1-300 (lower floor allows 1hr-video full zoom-out)", () => {
    // 2026-05-22 — floor reduced from 25 → 0.1 px/sec so a multi-minute
    // / multi-hour clip can fully zoom out (1300 px viewport / 3600 s =
    // 0.36 px/s for a 1 hr clip). UI-level minZoom is computed from the
    // actual clip duration inside TimelineZoomControl; the reducer's
    // floor only prevents negative or non-finite zooms.
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.setZoom(-5));
    expect(result.current.state.zoom).toBe(0.1);
    act(() => result.current.setZoom(500));
    expect(result.current.state.zoom).toBe(300);
  });

  it("addOverlayAtPlayhead creates an empty overlay at the playhead and selects it", () => {
    const { result } = renderHook(() => useEditorState());
    act(() =>
      result.current.initFromScenes("v", "gdrive", [
        makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 10_000 }),
      ]),
    );
    act(() => result.current.setPlayhead(2000));

    expect(result.current.state.subtitles).toHaveLength(0);

    act(() => result.current.addOverlayAtPlayhead());

    expect(result.current.state.subtitles).toHaveLength(1);
    const sub = result.current.state.subtitles[0];
    expect(sub.text).toBe("");
    expect(sub.startMs).toBe(2000);
    expect(sub.endMs).toBeGreaterThan(sub.startMs);
    expect(result.current.state.selectedSubtitleIndex).toBe(0);
    expect(result.current.state.isDirty).toBe(true);
  });

  it("addOverlayAtPlayhead clamps end_ms to total duration", () => {
    const { result } = renderHook(() => useEditorState());
    act(() =>
      result.current.initFromScenes("v", "gdrive", [
        makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 4_000 }),
      ]),
    );
    act(() => result.current.setPlayhead(3500));

    act(() => result.current.addOverlayAtPlayhead());

    const sub = result.current.state.subtitles[0];
    expect(sub.endMs).toBeLessThanOrEqual(result.current.state.totalDurationMs);
  });

  it("MARK_CLEAN resets isDirty", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.addClip(makeClip({ id: "c2" })));
    expect(result.current.state.isDirty).toBe(true);
    act(() => result.current.markClean());
    expect(result.current.state.isDirty).toBe(false);
  });
});

describe("createClipFromScene", () => {
  it("creates a clip from a scene object", () => {
    const scene = { scene_id: "s1", start_ms: 1000, end_ms: 4000 };
    const clip = createClipFromScene(scene, "gd_video", "gdrive");

    expect(clip.sceneId).toBe("s1");
    expect(clip.videoId).toBe("gd_video");
    expect(clip.originalStartMs).toBe(1000);
    expect(clip.originalEndMs).toBe(4000);
    expect(clip.trimStartMs).toBe(1000);
    expect(clip.trimEndMs).toBe(4000);
    expect(clip.volume).toBe(1.0);
    expect(clip.id).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// PR #255 — new reducer actions
// ---------------------------------------------------------------------------

import type { EditorSubtitle, LayerOrderId } from "../lib/types";
import type { EditorOverlay } from "../lib/overlay-types";
import { DEFAULT_SUBTITLE_STYLE } from "../constants";

function makeSub(overrides: Partial<EditorSubtitle> = {}): EditorSubtitle {
  return {
    id: `sub_${Math.random()}`,
    text: "hello",
    startMs: 0,
    endMs: 1000,
    style: { ...DEFAULT_SUBTITLE_STYLE },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// MOVE_CLIP
// ---------------------------------------------------------------------------

describe("MOVE_CLIP", () => {
  it("shifts subtitles inside the old window by the same delta", () => {
    const { result } = renderHook(() => useEditorState());
    // clip: 0..5000 on timeline
    const clip = makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 5000, timelineStartMs: 0 });
    act(() => result.current.initFromScenes("v", "gdrive", [clip]));
    // subtitle inside the window
    act(() => result.current.addSubtitle(makeSub({ startMs: 1000, endMs: 2000 })));
    // subtitle outside the window
    act(() => result.current.addSubtitle(makeSub({ startMs: 6000, endMs: 7000 })));

    act(() => result.current.moveClip(0, 3000));

    const delta = 3000;
    expect(result.current.state.subtitles[0].startMs).toBe(1000 + delta);
    expect(result.current.state.subtitles[0].endMs).toBe(2000 + delta);
    // out-of-window subtitle stays put
    expect(result.current.state.subtitles[1].startMs).toBe(6000);
    expect(result.current.state.subtitles[1].endMs).toBe(7000);
  });

  it("shifts overlays inside the old window and leaves out-of-window overlays unchanged", () => {
    const { result } = renderHook(() => useEditorState());
    const clip = makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 5000, timelineStartMs: 0 });
    act(() => result.current.initFromScenes("v", "gdrive", [clip]));
    act(() => result.current.addBackgroundOverlayAtPlayhead());
    // The addBackgroundOverlayAtPlayhead uses totalDurationMs=5000 so startMs=0, endMs=5000 (full clip).
    // Add a second overlay via direct dispatch that is outside the window.
    act(() =>
      result.current.dispatch({
        type: "ADD_OVERLAY",
        overlay: {
          kind: "background",
          id: "ov_out",
          startMs: 6000,
          endMs: 8000,
          layerIndex: 1,
          transform: { x: 0.5, y: 0.5, rotationDeg: 0, widthPx: 100, heightPx: 100 },
          effects: { opacity: 1, stroke: null, shadow: null },
          fillColor: "#ff0000",
          imageUrl: null,
        } as EditorOverlay,
      }),
    );

    act(() => result.current.moveClip(0, 2000));

    const delta = 2000;
    // First overlay was inside [0, 5000] → shifted
    const inWindow = result.current.state.overlays.find((o) => o.id !== "ov_out")!;
    expect(inWindow.startMs).toBe(0 + delta);
    expect(inWindow.endMs).toBe(5000 + delta);
    // Second overlay is outside [0, 5000] → unchanged
    const outWindow = result.current.state.overlays.find((o) => o.id === "ov_out")!;
    expect(outWindow.startMs).toBe(6000);
    expect(outWindow.endMs).toBe(8000);
  });

  it("clamps timelineStartMs to >= 0", () => {
    const { result } = renderHook(() => useEditorState());
    const clip = makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 5000, timelineStartMs: 1000 });
    act(() => result.current.initFromScenes("v", "gdrive", [clip]));

    // Pass a negative value; reducer clamps to 0.
    act(() => result.current.moveClip(0, -500));

    expect(result.current.state.clips[0].timelineStartMs).toBe(0);
  });

  it("no-ops when delta is zero (move to current position leaves isDirty unchanged)", () => {
    const { result } = renderHook(() => useEditorState());
    // initFromScenes packs the clip at timelineStartMs=0 via recomputeTimeline.
    const clip = makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 5000, timelineStartMs: 0 });
    act(() => result.current.initFromScenes("v", "gdrive", [clip]));
    expect(result.current.state.clips[0].timelineStartMs).toBe(0);
    expect(result.current.state.isDirty).toBe(false);

    // Move to the exact current position → delta=0 → reducer returns state
    // unchanged, isDirty stays false.
    act(() => result.current.moveClip(0, 0));

    expect(result.current.state.isDirty).toBe(false);
    expect(result.current.state.clips[0].timelineStartMs).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// SELECT_VIDEO / SELECT_LETTERBOX — mutual-exclusion model
// ---------------------------------------------------------------------------

describe("SELECT_VIDEO", () => {
  it("active=true clears selectedOverlayId, selectedSubtitleIndex, selectedClipIndex, selectedLetterbox", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    // Set up sibling selections
    act(() => result.current.selectClip(0));
    act(() => result.current.selectSubtitle(0));
    act(() => result.current.addBackgroundOverlayAtPlayhead());
    const overlayId = result.current.state.overlays[0].id;
    act(() => result.current.selectOverlay(overlayId));
    act(() => result.current.dispatch({ type: "SELECT_LETTERBOX", active: true }));

    act(() => result.current.dispatch({ type: "SELECT_VIDEO", active: true }));

    expect(result.current.state.selectedVideo).toBe(true);
    expect(result.current.state.selectedClipIndex).toBeNull();
    expect(result.current.state.selectedSubtitleIndex).toBeNull();
    expect(result.current.state.selectedOverlayId).toBeNull();
    expect(result.current.state.selectedLetterbox).toBe(false);
  });

  it("active=false only clears the video slot, leaves others untouched", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    // Start with video selected
    act(() => result.current.dispatch({ type: "SELECT_VIDEO", active: true }));
    expect(result.current.state.selectedVideo).toBe(true);

    // Now deselect video without touching clip selection
    act(() => result.current.selectClip(0));
    act(() => result.current.dispatch({ type: "SELECT_VIDEO", active: false }));

    expect(result.current.state.selectedVideo).toBe(false);
    // clip selection was set independently after the SELECT_VIDEO true,
    // and SELECT_VIDEO false must not clear it
    expect(result.current.state.selectedClipIndex).toBe(0);
  });
});

describe("SELECT_LETTERBOX", () => {
  it("active=true clears all other selection slots", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.selectClip(0));
    act(() => result.current.dispatch({ type: "SELECT_VIDEO", active: true }));

    act(() => result.current.dispatch({ type: "SELECT_LETTERBOX", active: true }));

    expect(result.current.state.selectedLetterbox).toBe(true);
    expect(result.current.state.selectedClipIndex).toBeNull();
    expect(result.current.state.selectedSubtitleIndex).toBeNull();
    expect(result.current.state.selectedOverlayId).toBeNull();
    expect(result.current.state.selectedVideo).toBe(false);
  });

  it("active=false only clears the letterbox slot", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.dispatch({ type: "SELECT_LETTERBOX", active: true }));
    act(() => result.current.selectClip(0));

    act(() => result.current.dispatch({ type: "SELECT_LETTERBOX", active: false }));

    expect(result.current.state.selectedLetterbox).toBe(false);
    expect(result.current.state.selectedClipIndex).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// APPLY_COMPOSITION_TEMPLATE
// ---------------------------------------------------------------------------

import type { CompositionPresetPayload } from "../lib/overlay-types";

describe("APPLY_COMPOSITION_TEMPLATE", () => {
  function makeTemplatePayload(overrides: Partial<CompositionPresetPayload> = {}): CompositionPresetPayload {
    return {
      subtitleStyle: null,
      overlays: [],
      letterbox: null,
      videoTransform: { x: 0.5, y: 0.5, scale: 1, rotationDeg: 0, outline: null, shadow: null },
      ...overrides,
    };
  }

  it("merges subtitleStyle into every existing subtitle", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.addSubtitle(makeSub({ id: "s1", style: { ...DEFAULT_SUBTITLE_STYLE } })));
    act(() => result.current.addSubtitle(makeSub({ id: "s2", style: { ...DEFAULT_SUBTITLE_STYLE } })));

    act(() =>
      result.current.dispatch({
        type: "APPLY_COMPOSITION_TEMPLATE",
        payload: makeTemplatePayload({
          subtitleStyle: {
            fontFamily: "Noto Sans KR",
            fontSizePx: 48,
            fontColor: "#FF0000",
            fontWeight: 400,
            positionX: 0.3,
            positionY: 0.7,
            backgroundColor: null,
            backgroundOpacity: 0.5,
          },
        }),
      }),
    );

    for (const sub of result.current.state.subtitles) {
      expect(sub.style.fontFamily).toBe("Noto Sans KR");
      expect(sub.style.fontColor).toBe("#FF0000");
    }
    // text untouched
    expect(result.current.state.subtitles[0].text).toBe("hello");
  });

  it("appends overlays with new ids, timing shifted to playhead", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.setPlayhead(2000));

    const overlayPayload: CompositionPresetPayload["overlays"] = [
      {
        kind: "background",
        layerIndex: 0,
        durationMs: 3000,
        payload: {
          fillColor: "#000000",
          imageUrl: null,
          transform: { x: 0.5, y: 0.5, rotationDeg: 0, widthPx: 240, heightPx: 80 },
          effects: { opacity: 1, stroke: null, shadow: null },
        },
      },
    ];

    act(() =>
      result.current.dispatch({
        type: "APPLY_COMPOSITION_TEMPLATE",
        payload: makeTemplatePayload({ overlays: overlayPayload }),
      }),
    );

    expect(result.current.state.overlays).toHaveLength(1);
    const o = result.current.state.overlays[0];
    expect(o.startMs).toBe(2000); // playhead
    expect(o.endMs).toBe(2000 + 3000); // playhead + durationMs
    // Fresh id generated (not from payload)
    expect(o.id).toBeTruthy();
    expect(o.id).not.toBe("");
  });

  it("appended overlays have unique ids when multiple are appended", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    const overlayPayload: CompositionPresetPayload["overlays"] = [
      { kind: "background", layerIndex: 0, durationMs: 1000, payload: { fillColor: "#111", imageUrl: null, transform: { x: 0.5, y: 0.5, rotationDeg: 0, widthPx: 100, heightPx: 100 }, effects: { opacity: 1, stroke: null, shadow: null } } },
      { kind: "background", layerIndex: 1, durationMs: 1000, payload: { fillColor: "#222", imageUrl: null, transform: { x: 0.5, y: 0.5, rotationDeg: 0, widthPx: 100, heightPx: 100 }, effects: { opacity: 1, stroke: null, shadow: null } } },
    ];
    act(() =>
      result.current.dispatch({
        type: "APPLY_COMPOSITION_TEMPLATE",
        payload: makeTemplatePayload({ overlays: overlayPayload }),
      }),
    );
    const ids = result.current.state.overlays.map((o) => o.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("SETs letterbox when payload.letterbox is non-null, leaves existing when null", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    // Apply with a letterbox
    act(() =>
      result.current.dispatch({
        type: "APPLY_COMPOSITION_TEMPLATE",
        payload: makeTemplatePayload({
          letterbox: {
            topHeightPct: 10,
            bottomHeightPct: 15,
            fillColor: "#000000",
            borderColor: null,
            borderWidthPx: 0,
          },
        }),
      }),
    );
    expect(result.current.state.letterbox?.topHeightPct).toBe(10);
    expect(result.current.state.letterbox?.bottomHeightPct).toBe(15);

    // Apply with null letterbox — existing letterbox untouched
    act(() =>
      result.current.dispatch({
        type: "APPLY_COMPOSITION_TEMPLATE",
        payload: makeTemplatePayload({ letterbox: null }),
      }),
    );
    expect(result.current.state.letterbox?.topHeightPct).toBe(10);
  });

  it("overwrites videoTransform", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    act(() =>
      result.current.dispatch({
        type: "APPLY_COMPOSITION_TEMPLATE",
        payload: makeTemplatePayload({
          videoTransform: { x: 0.3, y: 0.7, scale: 1.5, rotationDeg: 45, outline: null, shadow: null },
        }),
      }),
    );

    expect(result.current.state.videoTransform.x).toBe(0.3);
    expect(result.current.state.videoTransform.y).toBe(0.7);
    expect(result.current.state.videoTransform.scale).toBe(1.5);
    expect(result.current.state.videoTransform.rotationDeg).toBe(45);
  });

  it("inserts a letterbox slot in layerOrder when letterbox newly added", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    expect(result.current.state.layerOrder.some((l) => l.kind === "letterbox")).toBe(false);

    act(() =>
      result.current.dispatch({
        type: "APPLY_COMPOSITION_TEMPLATE",
        payload: makeTemplatePayload({
          letterbox: { topHeightPct: 10, bottomHeightPct: 10, fillColor: "#000", borderColor: null, borderWidthPx: 0 },
        }),
      }),
    );

    expect(result.current.state.layerOrder.some((l) => l.kind === "letterbox")).toBe(true);
  });

  it("appended overlay ids appear in layerOrder", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    act(() =>
      result.current.dispatch({
        type: "APPLY_COMPOSITION_TEMPLATE",
        payload: makeTemplatePayload({
          overlays: [
            { kind: "background", layerIndex: 0, durationMs: 1000, payload: { fillColor: "#111", imageUrl: null, transform: { x: 0.5, y: 0.5, rotationDeg: 0, widthPx: 100, heightPx: 100 }, effects: { opacity: 1, stroke: null, shadow: null } } },
          ],
        }),
      }),
    );

    const overlayId = result.current.state.overlays[0].id;
    const inLayerOrder = result.current.state.layerOrder.some(
      (l) => l.kind === "overlay" && l.id === overlayId,
    );
    expect(inLayerOrder).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// INIT_FROM_COMPOSITION — legacy field defaults
// ---------------------------------------------------------------------------

describe("INIT_FROM_COMPOSITION", () => {
  it("fills rotationDeg=0 and shadow=null when missing from persisted videoTransform", () => {
    const { result } = renderHook(() => useEditorState());

    act(() =>
      result.current.dispatch({
        type: "INIT_FROM_COMPOSITION",
        state: {
          videoId: "v1",
          clips: [],
          subtitles: [],
          overlays: [],
          layerOrder: [{ kind: "video" as const }, { kind: "subtitles" as const }],
          videoTransform: {
            x: 0.4,
            y: 0.6,
            scale: 1.2,
            // rotationDeg and shadow intentionally omitted (legacy)
          },
          // Deliberately malformed (legacy) shape — route through `unknown` so
          // the test can feed a videoTransform missing rotationDeg/shadow and
          // assert the reducer backfills defaults.
        } as unknown as Partial<import("../lib/types").EditorState>,
      }),
    );

    expect(result.current.state.videoTransform.rotationDeg).toBe(0);
    expect(result.current.state.videoTransform.shadow).toBeNull();
    // Provided fields preserved
    expect(result.current.state.videoTransform.x).toBe(0.4);
    expect(result.current.state.videoTransform.scale).toBe(1.2);
  });

  it("rebuilds layerOrder from overlays + letterbox regardless of what was persisted", () => {
    const { result } = renderHook(() => useEditorState());

    act(() =>
      result.current.dispatch({
        type: "INIT_FROM_COMPOSITION",
        state: {
          videoId: "v1",
          clips: [],
          subtitles: [],
          overlays: [
            {
              kind: "background" as const,
              id: "ov_bg1",
              startMs: 0,
              endMs: 3000,
              layerIndex: 0,
              transform: { x: 0.5, y: 0.5, rotationDeg: 0, widthPx: 100, heightPx: 100 },
              effects: { opacity: 1, stroke: null, shadow: null },
              fillColor: "#000",
              imageUrl: null,
            },
          ],
          letterbox: {
            topHeightPct: 10,
            bottomHeightPct: 10,
            fillColor: "#000",
            borderColor: null,
            borderWidthPx: 0,
          },
          // Stale / wrong layerOrder persisted — should be rebuilt
          layerOrder: [{ kind: "video" as const }],
          videoTransform: { x: 0.5, y: 0.5, scale: 1, rotationDeg: 0, outline: null, shadow: null },
        } as Partial<import("../lib/types").EditorState>,
      }),
    );

    const kinds = result.current.state.layerOrder.map((l) => l.kind);
    expect(kinds).toContain("letterbox");
    expect(kinds).toContain("overlay");
    // video always first
    expect(kinds[0]).toBe("video");
  });
});

// ---------------------------------------------------------------------------
// REORDER_LAYER
// ---------------------------------------------------------------------------

describe("REORDER_LAYER", () => {
  it("'forward' moves the entry one step toward the top", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    // Default: [video, subtitles]. Move video forward → [subtitles, video].
    act(() =>
      result.current.dispatch({
        type: "REORDER_LAYER",
        layer: { kind: "video" },
        direction: "forward",
      }),
    );
    expect(result.current.state.layerOrder[0].kind).toBe("subtitles");
    expect(result.current.state.layerOrder[1].kind).toBe("video");
  });

  it("'backward' moves the entry one step toward the bottom", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    // Default: [video, subtitles]. Move subtitles backward → [subtitles, video].
    act(() =>
      result.current.dispatch({
        type: "REORDER_LAYER",
        layer: { kind: "subtitles" },
        direction: "backward",
      }),
    );
    expect(result.current.state.layerOrder[0].kind).toBe("subtitles");
    expect(result.current.state.layerOrder[1].kind).toBe("video");
  });

  it("no-ops when already at boundary (front/back)", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    const before = result.current.state.layerOrder.map((l) => l.kind).join(",");

    // video is already at bottom → backward is a no-op
    act(() =>
      result.current.dispatch({
        type: "REORDER_LAYER",
        layer: { kind: "video" },
        direction: "backward",
      }),
    );
    const after = result.current.state.layerOrder.map((l) => l.kind).join(",");
    expect(after).toBe(before);
    expect(result.current.state.isDirty).toBe(false);
  });

  it("'front' moves entry to top of stack", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() =>
      result.current.dispatch({
        type: "REORDER_LAYER",
        layer: { kind: "video" },
        direction: "front",
      }),
    );
    const order = result.current.state.layerOrder;
    expect(order[order.length - 1].kind).toBe("video");
  });

  it("'back' moves entry to bottom of stack", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() =>
      result.current.dispatch({
        type: "REORDER_LAYER",
        layer: { kind: "subtitles" },
        direction: "back",
      }),
    );
    expect(result.current.state.layerOrder[0].kind).toBe("subtitles");
  });
});

// ---------------------------------------------------------------------------
// SET_LETTERBOX
// ---------------------------------------------------------------------------

describe("SET_LETTERBOX", () => {
  it("inserts a letterbox slot in layerOrder when first added", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    expect(result.current.state.layerOrder.some((l) => l.kind === "letterbox")).toBe(false);

    act(() =>
      result.current.setLetterbox({
        topHeightPct: 10,
        bottomHeightPct: 10,
        fillColor: "#000000",
        borderColor: null,
        borderWidthPx: 0,
      }),
    );

    expect(result.current.state.layerOrder.some((l) => l.kind === "letterbox")).toBe(true);
  });

  it("clamps top/bottomHeightPct to [0, 50]", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    act(() =>
      result.current.setLetterbox({
        topHeightPct: 80,     // over limit → clamp to 50
        bottomHeightPct: -5,  // under limit → clamp to 0
        fillColor: "#000000",
        borderColor: null,
        borderWidthPx: 0,
      }),
    );

    expect(result.current.state.letterbox?.topHeightPct).toBe(50);
    expect(result.current.state.letterbox?.bottomHeightPct).toBe(0);
  });

  it("passing undefined removes the letterbox and strips its layer slot", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() =>
      result.current.setLetterbox({
        topHeightPct: 10,
        bottomHeightPct: 10,
        fillColor: "#000000",
        borderColor: null,
        borderWidthPx: 0,
      }),
    );
    expect(result.current.state.letterbox).toBeDefined();
    expect(result.current.state.layerOrder.some((l) => l.kind === "letterbox")).toBe(true);

    act(() => result.current.setLetterbox(undefined));

    expect(result.current.state.letterbox).toBeUndefined();
    expect(result.current.state.layerOrder.some((l) => l.kind === "letterbox")).toBe(false);
  });

  it("adjusting an existing letterbox does not duplicate the slot", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() =>
      result.current.setLetterbox({
        topHeightPct: 10,
        bottomHeightPct: 10,
        fillColor: "#000000",
        borderColor: null,
        borderWidthPx: 0,
      }),
    );
    act(() =>
      result.current.setLetterbox({
        topHeightPct: 20,
        bottomHeightPct: 15,
        fillColor: "#111111",
        borderColor: null,
        borderWidthPx: 0,
      }),
    );

    const letterboxSlots = result.current.state.layerOrder.filter((l) => l.kind === "letterbox");
    expect(letterboxSlots).toHaveLength(1);
    expect(result.current.state.letterbox?.topHeightPct).toBe(20);
  });
});

// ---------------------------------------------------------------------------
// UPDATE_VIDEO_ROTATION / SET_VIDEO_SHADOW / SET_VIDEO_OUTLINE
// ---------------------------------------------------------------------------

describe("UPDATE_VIDEO_ROTATION", () => {
  it("clamps to [-360, 360]", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    act(() => result.current.updateVideoRotation(999));
    expect(result.current.state.videoTransform.rotationDeg).toBe(360);

    act(() => result.current.updateVideoRotation(-999));
    expect(result.current.state.videoTransform.rotationDeg).toBe(-360);

    act(() => result.current.updateVideoRotation(90));
    expect(result.current.state.videoTransform.rotationDeg).toBe(90);
  });
});

describe("SET_VIDEO_SHADOW", () => {
  it("clamps offsetX/offsetY to [-100, 100] and blurPx to [0, 200]", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    act(() =>
      result.current.dispatch({
        type: "SET_VIDEO_SHADOW",
        shadow: {
          color: "#000000",
          offsetX: 999,
          offsetY: -999,
          blurPx: 500,
          spreadPx: 200,
        },
      }),
    );

    const s = result.current.state.videoTransform.shadow!;
    expect(s.offsetX).toBe(100);
    expect(s.offsetY).toBe(-100);
    expect(s.blurPx).toBe(200);
    expect(s.spreadPx).toBe(100);
  });

  it("null clears the shadow", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() =>
      result.current.dispatch({
        type: "SET_VIDEO_SHADOW",
        shadow: { color: "#000", offsetX: 5, offsetY: 5, blurPx: 10, spreadPx: 0 },
      }),
    );
    expect(result.current.state.videoTransform.shadow).not.toBeNull();

    act(() => result.current.dispatch({ type: "SET_VIDEO_SHADOW", shadow: null }));
    expect(result.current.state.videoTransform.shadow).toBeNull();
  });
});

describe("SET_VIDEO_OUTLINE", () => {
  it("null clears the outline", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() =>
      result.current.dispatch({
        type: "SET_VIDEO_OUTLINE",
        outline: { color: "#FF0000", widthPx: 5 },
      }),
    );
    expect(result.current.state.videoTransform.outline).not.toBeNull();

    act(() => result.current.dispatch({ type: "SET_VIDEO_OUTLINE", outline: null }));
    expect(result.current.state.videoTransform.outline).toBeNull();
  });

  it("clamps widthPx to [0, 50]", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    act(() =>
      result.current.dispatch({
        type: "SET_VIDEO_OUTLINE",
        outline: { color: "#FF0000", widthPx: 999 },
      }),
    );
    expect(result.current.state.videoTransform.outline?.widthPx).toBe(50);

    act(() =>
      result.current.dispatch({
        type: "SET_VIDEO_OUTLINE",
        outline: { color: "#FF0000", widthPx: -5 },
      }),
    );
    expect(result.current.state.videoTransform.outline?.widthPx).toBe(0);
  });
});
