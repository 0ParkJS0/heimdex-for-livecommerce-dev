"use client";

// figma: 1602:41198 (배경 섹션) / 1607:65302 (텍스트·템플릿 패널)
// 변형 섹션 — 위치 X/Y + 회전°. 배경 패널에선 크기 W/H 추가.
// X/Y w=97 h=40, 회전 w=53 h=40, gap=8. radius·padding 은 NumericStepper primitive 위임.

import { ValueBox, ValueBoxXY, ValueBoxWH } from "../primitives/ValueBox";
import { t } from "../../lib/i18n/strings";
import type { EditorOverlay, TransformProps } from "../../lib/overlay-types";

interface TransformSectionProps {
  overlay: EditorOverlay;
  onChange: (transform: TransformProps) => void;
}

/**
 * Transform: position (X/Y as %, since the spec stores normalized 0-1)
 * + rotation in degrees. Background overlays additionally show width/height
 * in absolute pixels.
 */
export function TransformSection({ overlay, onChange }: TransformSectionProps) {
  const tf = overlay.transform;

  const updateTransform = (patch: Partial<TransformProps>) => {
    onChange({ ...tf, ...patch });
  };

  const xPct = Math.round(tf.x * 100);
  const yPct = Math.round(tf.y * 100);
  const rotInt = Math.round(tf.rotationDeg);

  // figma 2026-05-18 redesign — split the row under the 변형 header into two
  // sub-labelled columns: position (X/Y) and rotation (°). Background
  // overlays add an extra size (W/H) row below. The earlier "위치/회전"
  // single-row layout with three steppers did not match the goal capture.
  return (
    <section className="space-y-2.5">
      {/* figma 2015:249496 — section header: 14px SemiBold, tracking -0.35px */}
      <header className="text-[14px] font-semibold leading-[1.4] tracking-[-0.35px] text-grayscale-800">
        {t.transform.sectionLabel}
      </header>

      {/* figma 2015:249496 — for background overlays: 크기 (W/H) row
          appears ABOVE 위치 + 회전, matching the Figma 배경 tab spec.
          Text overlays keep the original 위치/회전-only layout. */}
      {overlay.kind === "background" && (
        <div className="flex flex-col gap-1">
          <span className="text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-grayscale-500">
            {t.transform.size}
          </span>
          <ValueBoxWH
            width={tf.widthPx ?? 0}
            height={tf.heightPx ?? 0}
            min={1}
            max={10000}
            onChangeWidth={(v) => updateTransform({ widthPx: v })}
            onChangeHeight={(v) => updateTransform({ heightPx: v })}
            ariaLabel={t.transform.size}
          />
        </div>
      )}

      {/* Position + rotation row: 위치 (X/Y) + 회전 (°) side by side.
          min-w-0 on the 1fr cell stops browser input min-width from
          overflowing the grid column boundary. 회전 cell trimmed to
          50 px so 위치 picks up ~10 px more breathing room — operator
          feedback at 1440 viewport. */}
      <div className="grid grid-cols-[1fr_50px] gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-grayscale-500">
            위치
          </span>
          <ValueBoxXY
            x={xPct}
            y={yPct}
            min={0}
            max={100}
            onChangeX={(v) => updateTransform({ x: v / 100 })}
            onChangeY={(v) => updateTransform({ y: v / 100 })}
            ariaLabel="overlay position"
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-grayscale-500">
            회전
          </span>
          <ValueBox
            value={rotInt}
            min={-360}
            max={360}
            onChange={(v) => updateTransform({ rotationDeg: v })}
            suffix="°"
            ariaLabel="overlay rotation"
            className="px-1"
          />
        </div>
      </div>
    </section>
  );
}
