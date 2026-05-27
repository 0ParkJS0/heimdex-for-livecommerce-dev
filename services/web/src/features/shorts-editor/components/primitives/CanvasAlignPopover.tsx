"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlignCenterHorizontal,
  AlignCenterVertical,
  AlignEndHorizontal,
  AlignEndVertical,
  AlignStartHorizontal,
  AlignStartVertical,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { ChevronDownIcon } from "./icons";
import { ToolbarButton } from "./ToolbarButton";
import type {
  CanvasAlignAxis,
  CanvasAlignPosition,
} from "../../lib/canvas-align";

interface CanvasAlignPopoverProps {
  onAlign: (axis: CanvasAlignAxis, position: CanvasAlignPosition) => void;
  // 2026-05-24 — selection-based routing model in the background panel
  // dims the popover when no element is selected (or the selected
  // element doesn't expose canvas-align — e.g. letterbox). Dimmed +
  // pointer-events-off matches the existing ToolbarButton disabled
  // style so the operator can see the panel structure stays consistent.
  disabled?: boolean;
}

interface AlignOption {
  axis: CanvasAlignAxis;
  position: CanvasAlignPosition;
  label: string;
  Icon: typeof AlignStartVertical;
}

// Row 1 — vertical-axis options control transform.x (horizontal placement
// of the overlay). Lucide's ``align-*-vertical`` glyphs read as "align to
// the left / center / right vertical line", which matches the operator's
// mental model: pick a vertical guide, send the overlay there.
const HORIZONTAL_OPTIONS: AlignOption[] = [
  {
    axis: "x",
    position: "start",
    label: "왼쪽 정렬",
    Icon: AlignStartVertical,
  },
  {
    axis: "x",
    position: "center",
    label: "가로 중앙 정렬",
    Icon: AlignCenterVertical,
  },
  {
    axis: "x",
    position: "end",
    label: "오른쪽 정렬",
    Icon: AlignEndVertical,
  },
];

// Row 2 — horizontal-axis options control transform.y (vertical placement).
const VERTICAL_OPTIONS: AlignOption[] = [
  {
    axis: "y",
    position: "start",
    label: "위쪽 정렬",
    Icon: AlignStartHorizontal,
  },
  {
    axis: "y",
    position: "center",
    label: "세로 중앙 정렬",
    Icon: AlignCenterHorizontal,
  },
  {
    axis: "y",
    position: "end",
    label: "아래쪽 정렬",
    Icon: AlignEndHorizontal,
  },
];

/**
 * Six-direction canvas alignment popover.
 *
 * Trigger button shows the lucide ``align-center-vertical`` icon (same
 * glyph the previous single-button canvas-align used). Clicking opens a
 * small popover with two rows of three buttons:
 *   row 1: x-axis — left / horizontal-center / right
 *   row 2: y-axis — top / vertical-center / bottom
 *
 * The popover anchors immediately under the trigger and closes on outside
 * click. Selecting an option calls ``onAlign(axis, position)`` so the
 * toolbar caller can decide how to compute the actual normalized target
 * (anchor correction lives in lib/canvas-align.ts).
 */
export function CanvasAlignPopover({ onAlign, disabled = false }: CanvasAlignPopoverProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (popoverRef.current?.contains(target)) return;
      if (triggerRef.current?.contains(target)) return;
      setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  // Auto-close the popover when the toolbar transitions to disabled
  // (e.g. operator clicked off the selected element while the popover
  // was open) so we don't leave a phantom dropdown hanging.
  useEffect(() => {
    if (disabled && open) setOpen(false);
  }, [disabled, open]);

  const handleSelect = (axis: CanvasAlignAxis, position: CanvasAlignPosition) => {
    onAlign(axis, position);
    setOpen(false);
  };

  return (
    <div ref={triggerRef} className="relative">
      {/* Figma 2015:246597 — trigger is a 54×28 row (p-[4px] + two
          20 px glyphs + gap-[6px]). Operator request 2026-05-24: the
          hover rectangle should sit 4 px past the icon on each side
          (~8 px wider total) so the affordance reads as "click me"
          and isn't visually pinched against the glyph. px-1 + the
          icon/chevron flex row inside extend the hover-bg rectangle
          by the requested amount without shifting the icon centre. */}
      <ToolbarButton
        ariaLabel="화면 정렬"
        active={open}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className="w-auto px-1"
      >
        <span className="flex items-center gap-1">
          <AlignCenterVertical className="h-4 w-4" />
          <ChevronDownIcon className="h-3 w-3" />
        </span>
      </ToolbarButton>

      {open && (
        <div
          ref={popoverRef}
          role="dialog"
          aria-label="화면 정렬 옵션"
          className={cn(
            "absolute right-0 top-full z-30 mt-1 flex flex-col gap-1",
            "rounded-[8px] border border-grayscale-200 bg-white p-1.5 shadow-md",
          )}
        >
          <div className="flex items-center gap-1">
            {HORIZONTAL_OPTIONS.map(({ axis, position, label, Icon }) => (
              <button
                key={`${axis}-${position}`}
                type="button"
                aria-label={label}
                title={label}
                onClick={() => handleSelect(axis, position)}
                className="flex h-7 w-7 items-center justify-center rounded-[6px] text-grayscale-500 transition-colors hover:bg-grayscale-100 hover:text-grayscale-800"
              >
                <Icon className="h-4 w-4" />
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            {VERTICAL_OPTIONS.map(({ axis, position, label, Icon }) => (
              <button
                key={`${axis}-${position}`}
                type="button"
                aria-label={label}
                title={label}
                onClick={() => handleSelect(axis, position)}
                className="flex h-7 w-7 items-center justify-center rounded-[6px] text-grayscale-500 transition-colors hover:bg-grayscale-100 hover:text-grayscale-800"
              >
                <Icon className="h-4 w-4" />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
