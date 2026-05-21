"use client";

// figma: 1713:275432  (cache: .figma-cache/1713-275432_phase5_editor-3.api.json)
// node-name: 배경 툴바 (line-spacing placeholder + layer order + fill color)
// spec: gap=1 (mx-1 separator), radius·padding 은 ToolbarButton/Dropdown primitive 사용

import { BringToFront, SendToBack } from "lucide-react";

import { CanvasAlignPopover } from "../primitives/CanvasAlignPopover";
import { ColorSwatchButton } from "../primitives/ColorSwatchButton";
import { ToolbarButton } from "../primitives/ToolbarButton";
import {
  computeCanvasAlignTarget,
  type CanvasAlignAxis,
  type CanvasAlignPosition,
} from "../../lib/canvas-align";
import { t } from "../../lib/i18n/strings";
import type { EditorBackgroundOverlay } from "../../lib/overlay-types";

interface BackgroundToolbarProps {
  overlay: EditorBackgroundOverlay;
  onChange: (updates: Partial<EditorBackgroundOverlay>) => void;
  onReorder: (direction: "front" | "back" | "forward" | "backward") => void;
}

/**
 * Background tab toolbar — canvas alignment + layer order + fill color.
 *
 * 2026-05-20 redesign — replaced the single-button align cycle with a
 * six-direction CanvasAlignPopover, and dropped the layer-order dropdown
 * ("부가설명 박스") plus its forward/backward middle steps. Layer order
 * now exposes only the two lucide affordances the operator wanted:
 * bring-to-front and send-to-back.
 */
export function BackgroundToolbar({
  overlay,
  onChange,
  onReorder,
}: BackgroundToolbarProps) {
  const handleCanvasAlign = (
    axis: CanvasAlignAxis,
    position: CanvasAlignPosition,
  ) => {
    const next = computeCanvasAlignTarget(overlay.id, axis, position);
    onChange({
      transform: { ...overlay.transform, [axis]: next },
    });
  };

  return (
    <div className="flex items-center justify-end gap-1">
      <CanvasAlignPopover onAlign={handleCanvasAlign} />

      <span className="mx-1 h-5 w-px bg-grayscale-100" />

      <ToolbarButton
        ariaLabel={t.background.bringToFront}
        onClick={() => onReorder("front")}
      >
        <BringToFront className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        ariaLabel={t.background.sendToBack}
        onClick={() => onReorder("back")}
      >
        <SendToBack className="h-4 w-4" />
      </ToolbarButton>

      <span className="mx-1 h-5 w-px bg-grayscale-100" />

      <ColorSwatchButton
        color={overlay.fillColor}
        onChange={(color) => onChange({ fillColor: color })}
        ariaLabel={t.background.fillColor}
        size="sm"
      />
    </div>
  );
}
