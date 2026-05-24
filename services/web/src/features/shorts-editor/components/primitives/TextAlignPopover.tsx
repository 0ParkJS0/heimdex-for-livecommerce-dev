"use client";

// figma 2031:329014~329023 — 텍스트 정렬 dropdown.
// Trigger button shows the currently selected align glyph + a chevron-down;
// clicking opens a small popover with the three lucide text-align icons
// (start / center / end). Picking one updates overlay.textAlign and closes
// the popover. Mirrors CanvasAlignPopover's UX so the operator's
// expectations carry across the toolbar.

import { useEffect, useRef, useState } from "react";
import {
  TextAlignCenter,
  TextAlignEnd,
  TextAlignStart,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { ChevronDownIcon } from "./icons";
import { ToolbarButton } from "./ToolbarButton";

type TextAlign = "left" | "center" | "right";

interface TextAlignPopoverProps {
  value: TextAlign;
  onChange: (next: TextAlign) => void;
}

interface AlignOption {
  value: TextAlign;
  label: string;
  Icon: typeof TextAlignStart;
}

const OPTIONS: AlignOption[] = [
  { value: "left", label: "왼쪽 정렬", Icon: TextAlignStart },
  { value: "center", label: "가운데 정렬", Icon: TextAlignCenter },
  { value: "right", label: "오른쪽 정렬", Icon: TextAlignEnd },
];

export function TextAlignPopover({ value, onChange }: TextAlignPopoverProps) {
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

  const ActiveIcon =
    OPTIONS.find((o) => o.value === value)?.Icon ?? TextAlignCenter;

  return (
    <div ref={triggerRef} className="relative">
      {/* Figma 2015:246595 — trigger row mirrors the canvas-align /
          layer-order popovers: p-[4px] + 20 px glyph + gap-[6px] +
          chevron. Operator request 2026-05-24: hover rectangle should
          extend 4 px past the icon on each side (~8 px wider total),
          matching the sibling popovers. w-auto + px-1 produces the
          same visual delta without moving the icon's centre. */}
      <ToolbarButton
        ariaLabel="텍스트 정렬"
        active={open}
        onClick={() => setOpen((v) => !v)}
        className="w-auto px-1"
      >
        <span className="flex items-center gap-1">
          <ActiveIcon className="h-4 w-4" />
          <ChevronDownIcon className="h-3 w-3" />
        </span>
      </ToolbarButton>

      {open && (
        <div
          ref={popoverRef}
          role="dialog"
          aria-label="텍스트 정렬 옵션"
          className={cn(
            "absolute left-0 top-full z-30 mt-1 flex items-center gap-1",
            "rounded-[8px] border border-grayscale-200 bg-white p-1.5 shadow-md",
          )}
        >
          {OPTIONS.map(({ value: v, label, Icon }) => (
            <button
              key={v}
              type="button"
              aria-label={label}
              title={label}
              aria-pressed={v === value}
              onClick={() => {
                onChange(v);
                setOpen(false);
              }}
              className={cn(
                "flex h-7 w-7 items-center justify-center rounded-[6px] transition-colors",
                v === value
                  ? "bg-heimdex-navy-50 text-heimdex-navy-600"
                  : "text-grayscale-500 hover:bg-grayscale-100 hover:text-grayscale-800",
              )}
            >
              <Icon className="h-4 w-4" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
