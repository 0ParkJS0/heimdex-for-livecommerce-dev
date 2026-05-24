import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useEditorState } from "../hooks/useEditorState";
import type { EditorClip } from "../lib/types";

// PR 5 follow-up — hybrid undo/redo coverage for the complex actions
// that fall back to snapshot history (D5 = hybrid, D6 = per-action
// regression tests). Simple drag-style transforms keep their inverse
// entries (subtitle_style / subtitle_time / overlay_transform / etc)
// and are exercised by the existing useEditorState.test.ts suite.

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

describe("useEditorState — hybrid snapshot history", () => {
  it("addOverlayAtPlayhead → undo restores empty subtitles slot", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    expect(result.current.state.subtitles).toHaveLength(0);

    act(() => result.current.addOverlayAtPlayhead());
    expect(result.current.state.subtitles).toHaveLength(1);

    act(() => result.current.undo());
    expect(result.current.state.subtitles).toHaveLength(0);
  });

  it("addOverlayAtPlayhead → undo → redo re-adds the subtitle", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    act(() => result.current.addOverlayAtPlayhead());
    const addedId = result.current.state.subtitles[0].id;

    act(() => result.current.undo());
    expect(result.current.state.subtitles).toHaveLength(0);

    act(() => result.current.redo());
    expect(result.current.state.subtitles).toHaveLength(1);
    expect(result.current.state.subtitles[0].id).toBe(addedId);
  });

  it("removeSubtitle → undo restores the removed subtitle", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    act(() => result.current.addOverlayAtPlayhead());
    const beforeText = "before";
    act(() =>
      result.current.updateSubtitle(0, { text: beforeText }),
    );
    expect(result.current.state.subtitles[0].text).toBe(beforeText);

    act(() => result.current.removeSubtitle(0));
    expect(result.current.state.subtitles).toHaveLength(0);

    act(() => result.current.undo());
    expect(result.current.state.subtitles).toHaveLength(1);
    expect(result.current.state.subtitles[0].text).toBe(beforeText);
  });

  it("updateSubtitle text change → undo restores prior text", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.addOverlayAtPlayhead());

    act(() => result.current.updateSubtitle(0, { text: "hello" }));
    expect(result.current.state.subtitles[0].text).toBe("hello");

    act(() => result.current.updateSubtitle(0, { text: "hello world" }));
    expect(result.current.state.subtitles[0].text).toBe("hello world");

    act(() => result.current.undo());
    expect(result.current.state.subtitles[0].text).toBe("hello");
  });

  it("addBackgroundOverlayAtPlayhead → undo removes the background", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    expect(result.current.state.overlays).toHaveLength(0);

    act(() => result.current.addBackgroundOverlayAtPlayhead("#FF0000"));
    expect(result.current.state.overlays).toHaveLength(1);

    act(() => result.current.undo());
    expect(result.current.state.overlays).toHaveLength(0);
  });

  it("updateOverlay color change → undo restores prior fillColor", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.addBackgroundOverlayAtPlayhead("#FF0000"));
    const id = result.current.state.overlays[0].id;
    const initialColor = (
      result.current.state.overlays[0] as { fillColor: string }
    ).fillColor;

    act(() => result.current.updateOverlay(id, { fillColor: "#00FF00" }));
    expect(
      (result.current.state.overlays[0] as { fillColor: string }).fillColor,
    ).toBe("#00FF00");

    act(() => result.current.undo());
    expect(
      (result.current.state.overlays[0] as { fillColor: string }).fillColor,
    ).toBe(initialColor);
  });

  it("updateOverlay transform-only does NOT snapshot (drag path uses inverse history)", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.addBackgroundOverlayAtPlayhead("#FF0000"));

    const historyBefore = result.current.state.history.length;
    const overlay = result.current.state.overlays[0];

    act(() =>
      result.current.updateOverlay(overlay.id, {
        transform: { ...overlay.transform, x: 0.4 },
      }),
    );

    // No new history pushed — drag uses inverse entries via
    // pointerdown's pushHistory call instead.
    expect(result.current.state.history.length).toBe(historyBefore);
  });

  it("removeOverlay → undo restores the overlay", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.addBackgroundOverlayAtPlayhead("#FF0000"));
    const id = result.current.state.overlays[0].id;

    act(() => result.current.removeOverlay(id));
    expect(result.current.state.overlays).toHaveLength(0);

    act(() => result.current.undo());
    expect(result.current.state.overlays).toHaveLength(1);
    expect(result.current.state.overlays[0].id).toBe(id);
  });

  it("trimClip → undo restores prior trim window", () => {
    const { result } = renderHook(() => useEditorState());
    act(() =>
      result.current.initFromScenes("v", "gdrive", [
        makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 5000 }),
      ]),
    );

    act(() => result.current.trimClip(0, 1000, 4000));
    expect(result.current.state.clips[0].trimStartMs).toBe(1000);
    expect(result.current.state.clips[0].trimEndMs).toBe(4000);

    act(() => result.current.undo());
    expect(result.current.state.clips[0].trimStartMs).toBe(0);
    expect(result.current.state.clips[0].trimEndMs).toBe(5000);
  });

  it("reorderClips → undo restores original order", () => {
    const { result } = renderHook(() => useEditorState());
    act(() =>
      result.current.initFromScenes("v", "gdrive", [
        makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 2000 }),
        makeClip({ id: "c2", trimStartMs: 0, trimEndMs: 3000 }),
      ]),
    );
    const originalIds = result.current.state.clips.map((c) => c.id);

    act(() => result.current.reorderClips(0, 1));
    expect(result.current.state.clips.map((c) => c.id)).not.toEqual(originalIds);

    act(() => result.current.undo());
    expect(result.current.state.clips.map((c) => c.id)).toEqual(originalIds);
  });

  it("reorderOverlay → undo restores prior layer index", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.addBackgroundOverlayAtPlayhead("#FF0000"));
    act(() => result.current.addBackgroundOverlayAtPlayhead("#00FF00"));

    const firstId = result.current.state.overlays[0].id;
    const initialLayer = result.current.state.overlays[0].layerIndex;
    const historyBefore = result.current.state.history.length;

    act(() => result.current.reorderOverlay(firstId, "front"));
    // We snapshot even when the underlying reducer makes no
    // observable change (the REORDER_OVERLAY 'front' case happens to
    // be a no-op when the overlay is already at the highest layer;
    // pre-existing on main, see useEditorState.overlays.test.ts). What
    // we want to verify here is the snapshot-on-undo plumbing — that
    // pushSnapshot fired and undo restores to the captured state.
    expect(result.current.state.history.length).toBeGreaterThan(historyBefore);

    act(() => result.current.undo());
    const restoredLayer = result.current.state.overlays.find(
      (o) => o.id === firstId,
    )!.layerIndex;
    expect(restoredLayer).toBe(initialLayer);
  });

  it("snapshot undo preserves the redoHistory tail for round-trips", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    act(() => result.current.addOverlayAtPlayhead());
    act(() => result.current.addOverlayAtPlayhead());
    expect(result.current.state.subtitles).toHaveLength(2);

    act(() => result.current.undo());
    expect(result.current.state.subtitles).toHaveLength(1);
    expect(result.current.state.redoHistory).toHaveLength(1);

    act(() => result.current.undo());
    expect(result.current.state.subtitles).toHaveLength(0);
    expect(result.current.state.redoHistory).toHaveLength(2);

    act(() => result.current.redo());
    expect(result.current.state.subtitles).toHaveLength(1);

    act(() => result.current.redo());
    expect(result.current.state.subtitles).toHaveLength(2);
  });

  it("new mutation after undo invalidates the redo chain", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    act(() => result.current.addOverlayAtPlayhead());
    act(() => result.current.undo());
    expect(result.current.state.redoHistory).toHaveLength(1);

    act(() => result.current.addOverlayAtPlayhead());
    expect(result.current.state.redoHistory).toHaveLength(0);
  });
});
