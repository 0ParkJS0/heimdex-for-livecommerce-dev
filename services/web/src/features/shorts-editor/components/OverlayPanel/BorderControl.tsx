"use client";

// figma: 1602:41198 (배경 섹션) / 1607:65302 (텍스트·템플릿 패널)
// 윤곽선 컨트롤 — 굵기 NumericStepper + 색상 swatch
// BackgroundPanel + TextOverlayPanel 공용

import { cn } from "@/lib/utils";

import { ColorSwatchButton } from "../primitives/ColorSwatchButton";
import { NumericStepper } from "../primitives/NumericStepper";
import { t } from "../../lib/i18n/strings";

interface BorderControlProps {
  width: number;
  color: string;
  onWidthChange: (next: number) => void;
  onColorChange: (next: string) => void;
  /**
   * Optional click handler for opening a custom color picker dialog
   * (color picker dialog). When omitted the native picker handles
   * color change via onColorChange.
   */
  onColorClick?: () => void;
  disabled?: boolean;
  // When ``true``, the underlying overlay carries no stroke (effects.stroke
  // === null). The control still renders so the operator can dial a value
  // in — but the swatch dims and the value renders as 0 to signal "off."
  // Picking a colour through onColorChange materialises the stroke in
  // state with the caller's default width.
  strokeIsOff?: boolean;
}

/**
 * Border / stroke controls — width stepper + color swatch.
 *
 * Headless of effect state: callers decide when to render (e.g. only when
 * `effects.stroke != null`). This component owns no toggle; it's purely the
 * width + color row.
 */
export function BorderControl({
  width,
  color,
  onWidthChange,
  onColorChange,
  onColorClick,
  disabled = false,
  strokeIsOff = false,
}: BorderControlProps) {
  // Stepping 0.1 ten times leaves the JS float at 0.9999... instead of
  // 1 — round to two decimals on every commit so the rendered value
  // stays human-readable and the persisted widthPx doesn't carry that
  // drift into the wire format. Operator request 2026-05-24: 0.1 step
  // + 1-decimal display so super-thin outlines (0.1–0.9 px) are
  // dialable without forcing the operator to type a value.
  const commitWidth = (next: number) =>
    onWidthChange(Math.round(next * 100) / 100);
  return (
    <div className="flex flex-col gap-1">
      {/* figma 2015:249496 — sublabel: 12px Medium tracking-[-0.3px] */}
      <span className="text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-grayscale-500">{t.effects.width}</span>
      {/* 굵기 박스 + 색 swatch — operator request 2026-05-22: the
          stepper should match the 회전 box (60 × 36) and the gap to
          the swatch should match the 위치→회전 gap (8 px). The
          swatch falls back to the 'md' size (36×36) so both halves
          share a 36 px height and the row lines up with the 변형
          row's bottom edge. */}
      <div className="flex items-center gap-2">
        <NumericStepper
          value={width}
          min={0}
          max={50}
          step={0.1}
          decimals={1}
          onChange={commitWidth}
          unit="px"
          ariaLabel={`${t.effects.stroke} width`}
          disabled={disabled}
          variant="vertical"
          // 2026-05-22 — width bumped 60 → 72 so '00px' fits inside
          // the box (the legacy 60 px clipped at '0px' the moment the
          // operator typed a 2-digit value). decimals={1} renders the
          // value as "5.0", "0.3", etc so 0.1 steps are readable.
          className="w-[80px]"
        />
        {onColorClick ? (
          <button
            type="button"
            onClick={onColorClick}
            disabled={disabled}
            aria-label={`${t.effects.stroke} color`}
            className={cn(
              "h-10 w-10 shrink-0 rounded-lg border border-grayscale-200 bg-white p-1 disabled:cursor-not-allowed disabled:opacity-40",
              // OFF state: dim the swatch so the operator reads it as
              // "click me to enable stroke", not "this colour is
              // currently applied."
              strokeIsOff && "opacity-40",
            )}
          >
            <span
              className="block h-full w-full rounded"
              style={{ backgroundColor: color }}
            />
          </button>
        ) : (
          <ColorSwatchButton
            color={color}
            onChange={onColorChange}
            ariaLabel={`${t.effects.stroke} color`}
            size="lg"
            disabled={disabled}
            className={strokeIsOff ? "opacity-40" : undefined}
          />
        )}
      </div>
    </div>
  );
}
