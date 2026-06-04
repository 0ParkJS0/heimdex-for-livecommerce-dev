"use client";

// figma 2015:246602 — layer-order dropdown for the background tab
// toolbar. Trigger button = send-to-back icon + chevron-down; popover
// shows the two layer ops (맨 앞으로, 맨 뒤로). Mirrors
// CanvasAlignPopover's UX so the operator's mental model carries over.

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { ChevronDownIcon } from "./icons";
import { ToolbarButton } from "./ToolbarButton";

// 2026-06-04 — operator-supplied tabler glyphs replace lucide
// SendToBack / BringToFront. Same 16px footprint (h-4 w-4 via className)
// and currentColor stroke; only the drawing changed.
//   StackPushIcon = "맨 뒤로" (send-to-back)    ← tabler stack-push
//   StackPopIcon  = "맨 앞으로" (bring-to-front) ← tabler stack-pop
function StackPushIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.66667}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4.99967 8.33398L3.33301 9.16732L9.99967 12.5007L16.6663 9.16732L14.9997 8.33398M3.33301 12.5007L9.99967 15.834L16.6663 12.5007M9.99967 3.33398V9.16732M7.49967 6.66732L9.99967 9.16732L12.4997 6.66732" />
    </svg>
  );
}

function StackPopIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.66667}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5.83398 7.91732L3.33398 9.16732L10.0007 12.5007L16.6673 9.16732L14.1673 7.91732M3.33398 12.5007L10.0007 15.834L16.6673 12.5007M10.0007 9.16732V3.33398M12.5007 5.83398L10.0007 3.33398L7.50065 5.83398" />
    </svg>
  );
}

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
  Icon: (props: { className?: string }) => JSX.Element;
}> = [
  { direction: "front", label: "맨 앞으로", Icon: StackPopIcon },
  { direction: "back", label: "맨 뒤로", Icon: StackPushIcon },
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
          <StackPushIcon className="h-4 w-4" />
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
