"use client";

// figma: 1713:275432  (cache: .figma-cache/1713-275432_phase5_editor-3.api.json)
// node-name: 텍스트 툴바 (B/I/U + align + line-spacing + color + highlight)
// spec: gap=1 (separator=mx-1 1px), radius·padding 은 ToolbarButton/Dropdown primitive 사용

import { useRef, useState } from "react";
import {
  TextAlignCenter,
  TextAlignEnd,
  TextAlignStart,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { CanvasAlignPopover } from "../primitives/CanvasAlignPopover";
import { ColorPalettePopover } from "../primitives/ColorPalettePopover";
import { ColorPalettePortal } from "../primitives/ColorPalettePortal";
import {
  BoldIcon,
  ChevronDownIcon,
  ItalicIcon,
  PaintBucketIcon,
  UnderlineIcon,
} from "../primitives/icons";
import { ToolbarButton } from "../primitives/ToolbarButton";
import {
  computeCanvasAlignTarget,
  type CanvasAlignAxis,
  type CanvasAlignPosition,
} from "../../lib/canvas-align";
import { t } from "../../lib/i18n/strings";
import type { EditorTextOverlay } from "../../lib/overlay-types";

const DEFAULT_HIGHLIGHT = "#FFE600";

interface TextToolbarProps {
  overlay: EditorTextOverlay;
  onChange: (updates: Partial<EditorTextOverlay>) => void;
}

/**
 * B / I / U | text-align cycle | canvas-align cycle | font color | highlight.
 *
 * Bold is a binary toggle on font_weight (400 / 700) — matches V1's "보통/굵게"
 * behavior so existing presets keep applying cleanly. The line-spacing
 * dropdown was removed per 2026-05-18 figma redesign; lineHeight stays in
 * the data model with its default and can still be set via presets.
 */
export function TextToolbar({ overlay, onChange }: TextToolbarProps) {
  const isBold = overlay.fontWeight >= 600;

  const AlignIcon =
    overlay.textAlign === "left"
      ? TextAlignStart
      : overlay.textAlign === "right"
      ? TextAlignEnd
      : TextAlignCenter;

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
    // 2026-05-20 — operator review on text-tab feedback: B / I / U and
    // the align/canvas-align clusters should spread evenly across the
    // panel width instead of huddling at the left. ``justify-between``
    // pins the first and last elements to the wrapper edges and
    // distributes the rest evenly between them.
    <div className="flex w-full items-center justify-between">
      <ToolbarButton
        active={isBold}
        onClick={() => onChange({ fontWeight: isBold ? 400 : 700 })}
        ariaLabel={t.text.bold}
      >
        <BoldIcon />
      </ToolbarButton>
      <ToolbarButton
        active={overlay.italic}
        onClick={() => onChange({ italic: !overlay.italic })}
        ariaLabel={t.text.italic}
      >
        <ItalicIcon />
      </ToolbarButton>
      <ToolbarButton
        active={overlay.underline}
        onClick={() => onChange({ underline: !overlay.underline })}
        ariaLabel={t.text.underline}
      >
        <UnderlineIcon />
      </ToolbarButton>

      <span className="mx-1 h-5 w-px bg-grayscale-200" />

      {/* Text alignment cycle — clicking advances left → center → right.
          Icon swaps to the lucide text-align-start / center / end glyph
          matching the current state. */}
      <ToolbarButton
        ariaLabel={t.text.align}
        onClick={() => {
          const next: EditorTextOverlay["textAlign"] =
            overlay.textAlign === "left"
              ? "center"
              : overlay.textAlign === "center"
              ? "right"
              : "left";
          onChange({ textAlign: next });
        }}
      >
        <AlignIcon className="h-4 w-4" />
      </ToolbarButton>
      <button
        type="button"
        onClick={() => {
          const next: EditorTextOverlay["textAlign"] =
            overlay.textAlign === "left"
              ? "center"
              : overlay.textAlign === "center"
              ? "right"
              : "left";
          onChange({ textAlign: next });
        }}
        aria-label={`${t.text.align} expand`}
        className="text-grayscale-400 hover:text-grayscale-800"
      >
        <ChevronDownIcon className="h-3 w-3" />
      </button>

      {/* Canvas-level alignment popover — six lucide direction icons
          arranged as two rows (x-axis / y-axis). The popover's onAlign
          callback measures the overlay's rendered box so start/end land
          flush against the canvas edge (anchor-corrected, per the
          operator's 2026-05-20 "99% rule"). */}
      <CanvasAlignPopover onAlign={handleCanvasAlign} />

      <span className="mx-1 h-5 w-px bg-grayscale-200" />

      {/* figma 1602:40064 — font color trigger: "A" glyph above a thin
          color bar that previews the current value. Click opens the
          shared ColorPalettePopover. */}
      <ColorTriggerButton
        ariaLabel={t.text.color}
        color={overlay.fontColor}
        onChange={(color) => onChange({ fontColor: color })}
      >
        <span className="text-[18px] font-medium leading-[1.4] tracking-[-0.45px] text-grayscale-800">
          A
        </span>
      </ColorTriggerButton>

      {/* figma 1602:40066 — highlight color trigger: paint-bucket icon
          above its color bar. Picking white/transparent from the palette
          effectively disables the highlight. */}
      <ColorTriggerButton
        ariaLabel={t.text.highlight}
        color={overlay.highlightColor ?? DEFAULT_HIGHLIGHT}
        muted={overlay.highlightColor == null}
        onChange={(color) => onChange({ highlightColor: color })}
      >
        <PaintBucketIcon />
      </ColorTriggerButton>
    </div>
  );
}

// figma 1602:40063~1602:40070 — 텍스트 색상/하이라이트 트리거.
// 28×26 공간에 아이콘이 자리잡고 그 아래 4px 색상 바가 현재 값을 미리
// 보여준다. 클릭 시 ColorPalettePopover 가 자식 트리거 바로 아래에 뜬다.
function ColorTriggerButton({
  ariaLabel,
  color,
  onChange,
  children,
  muted = false,
}: {
  ariaLabel: string;
  color: string;
  onChange: (color: string) => void;
  children: React.ReactNode;
  muted?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex h-7 w-7 flex-col items-center justify-center gap-[2px] rounded"
      >
        <span
          className={cn(
            "flex h-5 w-5 items-center justify-center",
            muted && "opacity-60",
          )}
        >
          {children}
        </span>
        <span
          aria-hidden
          className="block h-[3px] w-[20px] rounded-[1px]"
          style={{ backgroundColor: muted ? "transparent" : color }}
        />
      </button>
      {open && (
        // Portalled so the popover escapes the right-wrapper's overflow
        // clip; ColorPalettePortal handles position + outside-click.
        <ColorPalettePortal anchorRef={buttonRef} onClose={() => setOpen(false)}>
          <ColorPalettePopover
            color={color}
            onChange={(next) => {
              onChange(next.toUpperCase());
              setOpen(false);
            }}
            onClose={() => setOpen(false)}
            showOpacity={false}
          />
        </ColorPalettePortal>
      )}
    </>
  );
}
