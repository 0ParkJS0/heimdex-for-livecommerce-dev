"use client";

import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

interface NumericStepperProps {
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string; // e.g. "px", "pt", "°"
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
  // Figma 2045:407072 (윤곽선 굵기) + 2045:407082 (그림자 확산) switched
  // the stepper's left/right minus-plus pair for a single chevron-up /
  // chevron-down stack on the right of the value. ``variant="vertical"``
  // selects that layout; default stays horizontal for callers that
  // haven't migrated yet (font size, etc).
  variant?: "horizontal" | "vertical";
  // Number of decimal places to show in the readout. ``0`` (default)
  // matches the legacy integer-only display (e.g. "12px"); ``1`` lets
  // callers expose 0.1 increments cleanly (e.g. "5.0", "0.3"). Typing
  // still accepts free-form decimal input — the value passed to
  // onChange is always the parsed number with no display rounding.
  decimals?: number;
}

/**
 * Stepper input. Two layouts:
 *
 *   horizontal (default): [-] [value unit] [+]
 *   vertical            : [value unit] [⌃⌄]
 *
 * Clicking the steppers nudges by `step`. Typing into the input commits on
 * blur or Enter. Values outside [min, max] are clamped before propagating,
 * so callers don't need defensive clamping.
 */
export function NumericStepper({
  value,
  onChange,
  min = -Infinity,
  max = Infinity,
  step = 1,
  unit,
  ariaLabel,
  disabled = false,
  className,
  variant = "horizontal",
  decimals = 0,
}: NumericStepperProps) {
  const clamp = (v: number) => Math.min(max, Math.max(min, v));
  // toFixed(decimals) keeps "5" rendering as "5.0" once the caller
  // opts into a 1-decimal display. JS float drift (0.1 + 0.2 = 0.3000…)
  // is also smoothed out here without changing the stored value.
  const formatValue = (v: number) =>
    decimals > 0 ? v.toFixed(decimals) : String(v);

  const valueInput = (
    <input
      type="text"
      inputMode="decimal"
      value={Number.isFinite(value) ? formatValue(value) : ""}
      onChange={(e) => {
        const raw = e.target.value.trim();
        const next = raw === "" ? min : Number(raw);
        if (!Number.isFinite(next)) return;
        onChange(clamp(next));
      }}
      disabled={disabled}
      className={cn(
        "min-w-0 border-x border-transparent bg-transparent py-1 text-[14px] tracking-[-0.35px] text-grayscale-800 focus:border-heimdex-navy-400 focus:outline-none disabled:cursor-not-allowed",
        // Vertical variant: input is flex-1 so the value fills the
        // remaining space inside the rounded box after the unit and
        // chevron stack. Without this, w-12 reserved 48 px and a
        // 2-digit value + 'px' suffix overflowed past the chevron
        // stack at w-[72px] wrapper widths.
        variant === "horizontal" ? "w-full text-center" : "min-w-0 flex-1 text-left",
      )}
    />
  );

  if (variant === "vertical") {
    // figma 2045:407072 — value + unit on the left, chevron-up / -down
    // stacked on the right inside one rounded-10 box. Height matches
    // ValueBox (h-9 / 36 px) so the 윤곽선 굵기 row lines up with the
    // 변형/회전 row visually — the previous h-10 + lg swatch combo
    // left the row standing 4 px taller than its 변형 neighbour.
    return (
      <div
        className={cn(
          // gap-1 (4 px) + px-1.5 (12 px) instead of gap-1.5 / px-2
          // saves ~8 px of internal chrome so a 2-digit value + 'px'
          // suffix + chevron stack fits in a 72–80 px wrapper.
          "flex h-10 items-center gap-1 rounded-[10px] border border-grayscale-300 bg-white px-1.5 py-0.5",
          disabled && "opacity-60",
          className,
        )}
        aria-label={ariaLabel}
      >
        {valueInput}
        {unit && (
          <span className="select-none text-[14px] tracking-[-0.35px] text-grayscale-800">
            {unit}
          </span>
        )}
        <div className="flex w-4 flex-col items-center">
          <button
            type="button"
            onClick={() => onChange(clamp(value + step))}
            disabled={disabled || value >= max}
            aria-label="증가"
            className="text-grayscale-700 transition-colors hover:text-grayscale-900 disabled:opacity-30"
          >
            <ChevronUp className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => onChange(clamp(value - step))}
            disabled={disabled || value <= min}
            aria-label="감소"
            className="text-grayscale-700 transition-colors hover:text-grayscale-900 disabled:opacity-30"
          >
            <ChevronDown className="h-4 w-4" />
          </button>
        </div>
      </div>
    );
  }

  return (
    // figma 1663:45782 — Accordion-style stepper: rounded-10 border
    // grayscale/300, minus/plus icons flank the centered value+unit.
    <div
      className={cn(
        "flex h-10 items-center rounded-[10px] border border-grayscale-300 bg-white",
        disabled && "opacity-60",
        className,
      )}
      aria-label={ariaLabel}
    >
      <button
        type="button"
        onClick={() => onChange(clamp(value - step))}
        disabled={disabled || value <= min}
        className="flex h-full w-8 items-center justify-center text-grayscale-500 transition-colors hover:text-grayscale-800 disabled:cursor-not-allowed disabled:text-grayscale-300"
        aria-label="감소"
      >
        −
      </button>
      {valueInput}
      {unit && (
        <span className="select-none px-1 text-[12px] text-grayscale-500">{unit}</span>
      )}
      <button
        type="button"
        onClick={() => onChange(clamp(value + step))}
        disabled={disabled || value >= max}
        className="flex h-full w-8 items-center justify-center text-grayscale-500 transition-colors hover:text-grayscale-800 disabled:cursor-not-allowed disabled:text-grayscale-300"
        aria-label="증가"
      >
        +
      </button>
    </div>
  );
}
