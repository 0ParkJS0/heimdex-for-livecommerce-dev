"use client";

// figma 2015:246602 — layer-order dropdown for the background tab
// toolbar. Trigger button = send-to-back icon + chevron-down; popover
// shows the two layer ops (맨 앞으로, 맨 뒤로). Mirrors
// CanvasAlignPopover's UX so the operator's mental model carries over.

import { useEffect, useRef, useState } from "react";
import { BringToFront, SendToBack } from "lucide-react";

import { cn } from "@/lib/utils";
import { ChevronDownIcon } from "./icons";
import { ToolbarButton } from "./ToolbarButton";

export type LayerOrderDirection = "front" | "back" | "forward" | "backward";

interface LayerOrderPopoverProps {
  onReorder: (direction: LayerOrderDirection) => void;
  // 2026-05-24 — disabled state mirrors CanvasAlignPopover so the
  // background-panel toolbar reads as inactive when no element is
  // selected (selection-based routing model).
  disabled?: boolean;
}

const OPTIONS: ReadonlyArray<{
  direction: LayerOrderDirection;
  label: string;
  Icon: typeof BringToFront;
}> = [
  { direction: "front", label: "맨 앞으로", Icon: BringToFront },
  { direction: "back", label: "맨 뒤로", Icon: SendToBack },
];

export function LayerOrderPopover({ onReorder, disabled = false }: LayerOrderPopoverProps) {
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

  // Auto-close on transition to disabled (mirrors CanvasAlignPopover).
  useEffect(() => {
    if (disabled && open) setOpen(false);
  }, [disabled, open]);

  const handleSelect = (direction: LayerOrderDirection) => {
    onReorder(direction);
    setOpen(false);
  };

  return (
    <div ref={triggerRef} className="relative">
      {/* Figma 2015:246603 — trigger is a 54×28 row (p-[4px] + two
          20 px glyphs + gap-[6px]). Operator request 2026-05-24: the
          hover rectangle should sit 4 px past the icon on each side
          (~8 px wider total). w-auto + px-1 extends the hover-bg
          beyond the icon centre without shifting layout. */}
      <ToolbarButton
        ariaLabel="레이어 순서"
        active={open}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className="w-auto px-1"
      >
        <span className="flex items-center gap-1">
          <SendToBack className="h-4 w-4" />
          <ChevronDownIcon className="h-3 w-3" />
        </span>
      </ToolbarButton>

      {open && (
        <div
          ref={popoverRef}
          role="dialog"
          aria-label="레이어 순서 옵션"
          className={cn(
            "absolute right-0 top-full z-30 mt-1 flex items-center gap-1",
            "rounded-[8px] border border-grayscale-200 bg-white p-1.5 shadow-md",
          )}
        >
          {OPTIONS.map(({ direction, label, Icon }) => (
            <button
              key={direction}
              type="button"
              aria-label={label}
              title={label}
              onClick={() => handleSelect(direction)}
              className="flex h-7 w-7 items-center justify-center rounded-[6px] text-grayscale-500 transition-colors hover:bg-grayscale-100 hover:text-grayscale-800"
            >
              <Icon className="h-4 w-4" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
