/**
 * Tests for the V2 overlay branches of the editor reducer.
 * Covers addTextOverlayAtPlayhead, addBackgroundOverlayAtPlayhead,
 * updateOverlay, removeOverlay, selectOverlay, reorderOverlay.
 */

import { renderHook, act } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useEditorState } from "../hooks/useEditorState";

function setupWithDuration(totalMs: number) {
  return renderHook(() => useEditorState());
}

describe("useEditorState — V2 overlays", () => {
  it("addTextOverlayAtPlayhead inserts a text overlay and selects it", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });

    expect(result.current.state.overlays).toHaveLength(1);
    expect(result.current.state.overlays[0].kind).toBe("text");
    expect(result.current.state.selectedOverlayId).toBe(
      result.current.state.overlays[0].id,
    );
    expect(result.current.state.isDirty).toBe(true);
  });

  it("addBackgroundOverlayAtPlayhead inserts a background overlay with W/H", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addBackgroundOverlayAtPlayhead();
    });

    const ov = result.current.state.overlays[0];
    expect(ov.kind).toBe("background");
    expect(ov.transform.widthPx).toBeGreaterThan(0);
    expect(ov.transform.heightPx).toBeGreaterThan(0);
  });

  it("updateOverlay merges fields and preserves identity", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });
    const id = result.current.state.overlays[0].id;

    act(() => {
      result.current.updateOverlay(id, { italic: true, underline: true });
    });

    const overlay = result.current.state.overlays[0];
    expect(overlay.id).toBe(id);
    expect(overlay.kind).toBe("text");
    if (overlay.kind === "text") {
      expect(overlay.italic).toBe(true);
      expect(overlay.underline).toBe(true);
    }
  });

  it("removeOverlay clears selection if it was selected", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });
    const id = result.current.state.overlays[0].id;

    act(() => {
      result.current.removeOverlay(id);
    });

    expect(result.current.state.overlays).toHaveLength(0);
    expect(result.current.state.selectedOverlayId).toBeNull();
  });

  it("selectOverlay clears clip + subtitle selection", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });
    const id = result.current.state.overlays[0].id;

    act(() => {
      result.current.selectOverlay(id);
    });

    expect(result.current.state.selectedOverlayId).toBe(id);
    expect(result.current.state.selectedClipIndex).toBeNull();
    expect(result.current.state.selectedSubtitleIndex).toBeNull();
  });

  it("reorderOverlay 'front' moves the overlay to the highest layer index", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });
    act(() => {
      result.current.addBackgroundOverlayAtPlayhead();
    });
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });

    const firstId = result.current.state.overlays[0].id;
    expect(result.current.state.overlays[0].layerIndex).toBe(0);

    act(() => {
      result.current.reorderOverlay(firstId, "front");
    });

    const moved = result.current.state.overlays.find((o) => o.id === firstId)!;
    // 'front' clamps to MAX_TEXT_OVERLAY_LAYER (1) per operator policy
    // 2026-05-24 (텍스트 row 최대 2개). Reducer applies the cap to all
    // overlays uniformly, so the highest reachable index via 'front' is 1.
    expect(moved.layerIndex).toBe(1);
  });

  it("reorderOverlay 'forward' is a single-step swap", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });
    act(() => {
      result.current.addBackgroundOverlayAtPlayhead();
    });
    const firstId = result.current.state.overlays[0].id;

    act(() => {
      result.current.reorderOverlay(firstId, "forward");
    });
    expect(
      result.current.state.overlays.find((o) => o.id === firstId)!.layerIndex,
    ).toBe(1);
  });
});

// B8 (2026-05-26) — bg/letterbox media-background segment policy.
// Default: a fresh background sits BELOW the letterbox (the operator's
// stated default after "send-to-front lifts above"). REORDER_LAYER on
// the background or the letterbox slot can re-stack the two within the
// segment — subtitles + text overlays stay pinned above either way.
describe("useEditorState — bg/letterbox layer policy (B8)", () => {
  function indexOfBg(
    layerOrder: ReturnType<typeof useEditorState>["state"]["layerOrder"],
    bgId: string,
  ): number {
    return layerOrder.findIndex(
      (l) => l.kind === "overlay" && l.id === bgId,
    );
  }
  function indexOfLetterbox(
    layerOrder: ReturnType<typeof useEditorState>["state"]["layerOrder"],
  ): number {
    return layerOrder.findIndex((l) => l.kind === "letterbox");
  }

  it("ADD background lands below an existing letterbox by default", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => {
      result.current.setLetterbox({
        topHeightPct: 10,
        bottomHeightPct: 10,
        fillColor: "#000000",
        borderColor: null,
        borderWidthPx: 0,
      });
    });
    act(() => result.current.addBackgroundOverlayAtPlayhead());

    const bgId = result.current.state.overlays.find(
      (o) => o.kind === "background",
    )!.id;
    const lo = result.current.state.layerOrder;
    expect(indexOfBg(lo, bgId)).toBeGreaterThan(0); // above video
    expect(indexOfBg(lo, bgId)).toBeLessThan(indexOfLetterbox(lo));
  });

  it("REORDER_LAYER 'front' on a background lifts it above the letterbox", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => {
      result.current.setLetterbox({
        topHeightPct: 10,
        bottomHeightPct: 10,
        fillColor: "#000000",
        borderColor: null,
        borderWidthPx: 0,
      });
    });
    act(() => result.current.addBackgroundOverlayAtPlayhead());
    const bgId = result.current.state.overlays.find(
      (o) => o.kind === "background",
    )!.id;

    act(() =>
      result.current.reorderLayer({ kind: "overlay", id: bgId }, "front"),
    );

    const lo = result.current.state.layerOrder;
    expect(indexOfBg(lo, bgId)).toBeGreaterThan(indexOfLetterbox(lo));
    // Subtitles + text overlays stay pinned above the media-bg segment.
    const subIdx = lo.findIndex((l) => l.kind === "subtitles");
    expect(indexOfBg(lo, bgId)).toBeLessThan(subIdx);
  });

  it("SET_LETTERBOX with existing backgrounds inserts letterbox above them", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.addBackgroundOverlayAtPlayhead());
    const bgId = result.current.state.overlays.find(
      (o) => o.kind === "background",
    )!.id;
    act(() => {
      result.current.setLetterbox({
        topHeightPct: 10,
        bottomHeightPct: 10,
        fillColor: "#000000",
        borderColor: null,
        borderWidthPx: 0,
      });
    });

    const lo = result.current.state.layerOrder;
    expect(indexOfBg(lo, bgId)).toBeLessThan(indexOfLetterbox(lo));
  });

  it("REORDER_LAYER 'back' on letterbox moves it below an existing background", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.addBackgroundOverlayAtPlayhead());
    const bgId = result.current.state.overlays.find(
      (o) => o.kind === "background",
    )!.id;
    act(() => {
      result.current.setLetterbox({
        topHeightPct: 10,
        bottomHeightPct: 10,
        fillColor: "#000000",
        borderColor: null,
        borderWidthPx: 0,
      });
    });

    act(() => result.current.reorderLayer({ kind: "letterbox" }, "back"));

    const lo = result.current.state.layerOrder;
    // Letterbox dropped into the media-bg band below the background.
    expect(indexOfLetterbox(lo)).toBeLessThan(indexOfBg(lo, bgId));
    // Subtitles still on top of the media-bg segment.
    const subIdx = lo.findIndex((l) => l.kind === "subtitles");
    expect(indexOfBg(lo, bgId)).toBeLessThan(subIdx);
  });
});
