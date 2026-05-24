"use client";

// figma 2015:249496 — 배경 패널 redesign (2026-05-22).
// Toolbar collapses to just two chevron-dropdown triggers:
//   * CanvasAlignPopover  (was 6 separate icons + 1 chevron in the
//     prior redesign — already compressed)
//   * LayerOrderPopover   (was 2 separate buttons bring/send — now
//     a single chevron dropdown with both ops inside)
// The fill-colour swatch was removed from the toolbar; colour control
// for the letterbox border lives in the 윤곽선 row in BackgroundPanel
// instead.
//
// 2026-05-24 — selection-based routing model. The toolbar no longer
// assumes an overlay is selected; callers pass the resolved
// ``onCanvasAlign`` / ``onReorder`` callbacks plus disabled flags so
// each popover can either operate on the currently-selected element
// (video / letterbox / overlay) or dim itself when no element is
// selected. The legacy ``overlay`` + ``onChange`` props are gone —
// the panel now derives the canvas-align target itself based on
// which selection slot is active.

import { CanvasAlignPopover } from "../primitives/CanvasAlignPopover";
import { LayerOrderPopover } from "../primitives/LayerOrderPopover";
import type {
  CanvasAlignAxis,
  CanvasAlignPosition,
} from "../../lib/canvas-align";

interface BackgroundToolbarProps {
  // Canvas-align route: BackgroundPanel resolves the axis/position to
  // the appropriate dispatch (overlay transform vs videoTransform).
  // ``canvasAlignDisabled`` greys out the popover when no element is
  // selected, or when the selected element doesn't expose canvas-align
  // (e.g. letterbox has no x/y to align).
  onCanvasAlign: (axis: CanvasAlignAxis, position: CanvasAlignPosition) => void;
  canvasAlignDisabled?: boolean;
  // Layer-order route: same shape as before. ``layerOrderDisabled``
  // greys out when no element is selected.
  onReorder: (direction: "front" | "back" | "forward" | "backward") => void;
  layerOrderDisabled?: boolean;
}

export function BackgroundToolbar({
  onCanvasAlign,
  canvasAlignDisabled = false,
  onReorder,
  layerOrderDisabled = false,
}: BackgroundToolbarProps) {
  return (
    <div className="flex items-center justify-end gap-1">
      <CanvasAlignPopover
        onAlign={onCanvasAlign}
        disabled={canvasAlignDisabled}
      />
      <LayerOrderPopover
        onReorder={onReorder}
        disabled={layerOrderDisabled}
      />
    </div>
  );
}
