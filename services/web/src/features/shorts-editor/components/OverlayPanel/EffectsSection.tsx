"use client";

// figma: 1602:41198 (배경 섹션) / 1607:65302 (텍스트·템플릿 패널 효과 영역)
// 효과 섹션 — 불투명도 LabeledSlider + 윤곽선(BorderControl) + 그림자(ShadowControl)
// 텍스트·배경 패널 공용. radius·padding 은 primitive 에 위임.

import { useEffect } from "react";
import { LabeledSlider } from "../primitives/LabeledSlider";
import { BorderControl } from "./BorderControl";
import { ShadowControl } from "./ShadowControl";
import { t } from "../../lib/i18n/strings";
import type {
  EffectsProps,
  ShadowProps,
  StrokeProps,
} from "../../lib/overlay-types";

interface EffectsSectionProps {
  effects: EffectsProps;
  onChange: (effects: EffectsProps) => void;
  // figma 1663:45821 / 1607:65622 — stroke is rendered alongside Transform
  // in a 2-col row, so EffectsSection skips it when the panel chooses to
  // host it separately.
  hideStroke?: boolean;
}

// Per operator request 2026-05-24: a freshly-added text overlay must
// render with stroke OFF (effects.stroke === null). The previous
// behaviour materialised DEFAULT_STROKE on mount, which produced a
// red 5 px outline before the operator had touched any control —
// reads as a bug the moment "+ 텍스트 추가" is clicked. Stroke is now
// opt-in: BorderControl shows widthPx=0 / no swatch until the operator
// picks a colour, at which point the stroke is materialised into
// state with width seeded to 5 px (DEFAULT_STROKE_WIDTH_PX).
//
// Shadow keeps its mount-time materialisation so the sliders show
// live values from the first paint. Operator request 2026-05-24:
// default is a simple drop shadow — black, +5/+5 offset, no blur,
// no spread — so the overlay reads as a duplicate glyph layer
// behind the foreground until the operator dials something else.
export const DEFAULT_STROKE_WIDTH_PX = 5;
const DEFAULT_SHADOW: ShadowProps = {
  color: "#000000",
  offsetX: 5,
  offsetY: 5,
  blurPx: 0,
  spreadPx: 0,
};
// Placeholder values rendered by BorderControl when stroke === null.
// The stepper still shows a number and the swatch a colour, but the
// underlying overlay carries no stroke until the operator interacts.
const STROKE_OFF_PLACEHOLDER: StrokeProps = {
  color: "#FF0000",
  widthPx: 0,
};

/**
 * Combined Opacity / Stroke / Shadow controls.
 *
 * Section-per-effect to mirror Figma 2026-05-18 redesign. ON/OFF toggles
 * were removed — all sub-controls render unconditionally. When the
 * underlying overlay has a null stroke / shadow we render the controls
 * against DEFAULT values; the first user interaction materialises the
 * effect in state. This matches the figma capture where every section
 * shows live values regardless of whether the user has enabled them yet.
 */
export function EffectsSection({ effects, onChange, hideStroke = false }: EffectsSectionProps) {
  const update = (patch: Partial<EffectsProps>) => {
    onChange({ ...effects, ...patch });
  };

  // Materialise SHADOW only into state on first render so the sliders
  // start from a non-null model and any drag immediately produces
  // visible CSS. Stroke stays opt-in (null) — BorderControl renders
  // the OFF placeholder when stroke is null and the first colour pick
  // materialises the stroke into state with the Q4 default width.
  useEffect(() => {
    if (effects.shadow === null) {
      onChange({
        ...effects,
        shadow: DEFAULT_SHADOW,
      });
    }
    // Only run on mount — intentionally excludes effects/onChange from
    // deps to avoid infinite update loops.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stroke = effects.stroke ?? STROKE_OFF_PLACEHOLDER;
  const shadow = effects.shadow ?? DEFAULT_SHADOW;
  const strokeOff = effects.stroke === null;

  return (
    <div className="space-y-4">
      {/* Opacity ------------------------------------------------------------- */}
      <section>
        <Header label={t.effects.opacity} />
        <LabeledSlider
          value={Math.round(effects.opacity * 100)}
          onChange={(v) => update({ opacity: v / 100 })}
          min={0}
          max={100}
          formatReadout={(v) => `${v}%`}
          ariaLabel={t.effects.opacity}
        />
      </section>

      {/* Stroke — hidden when the panel hosts it alongside Transform ------------
         BorderControl is headless of the OFF state; when stroke is null
         the controls render placeholder values (width 0, swatch shown
         as the placeholder hex) and the first colour pick materialises
         the stroke into state with the Q4 default width so the outline
         appears at a thin, readable thickness. Once materialised, width
         and colour edits flow through the normal patch path. */}
      {!hideStroke && (
        <section>
          <Header label={t.effects.stroke} />
          <BorderControl
            width={stroke.widthPx}
            color={stroke.color}
            strokeIsOff={strokeOff}
            onWidthChange={(widthPx) =>
              update({
                stroke: strokeOff
                  ? { color: stroke.color, widthPx }
                  : { ...stroke, widthPx },
              })
            }
            onColorChange={(color) =>
              update({
                stroke: strokeOff
                  ? { color, widthPx: DEFAULT_STROKE_WIDTH_PX }
                  : { ...stroke, color },
              })
            }
          />
        </section>
      )}

      {/* Shadow -------------------------------------------------------------- */}
      <section>
        <Header label={t.effects.shadow} />
        <ShadowControl
          offsetX={shadow.offsetX}
          offsetY={shadow.offsetY}
          spread={shadow.spreadPx}
          blur={shadow.blurPx}
          color={shadow.color}
          onChange={(next) =>
            update({
              shadow: {
                color: next.color,
                offsetX: next.offsetX,
                offsetY: next.offsetY,
                blurPx: next.blur,
                spreadPx: next.spread,
              },
            })
          }
        />
      </section>
    </div>
  );
}

// Standalone stroke section — same content as EffectsSection's stroke block.
// Used by panels that pair stroke with Transform in a 2-col row.
// Mirrors the OFF-state behaviour: when effects.stroke is null the
// controls render placeholder values and the first colour pick
// materialises the stroke into state.
export function StrokeBlock({
  effects,
  onChange,
}: {
  effects: EffectsProps;
  onChange: (effects: EffectsProps) => void;
}) {
  const stroke = effects.stroke ?? STROKE_OFF_PLACEHOLDER;
  const strokeOff = effects.stroke === null;
  return (
    <section>
      <Header label={t.effects.stroke} />
      <BorderControl
        width={stroke.widthPx}
        color={stroke.color}
        strokeIsOff={strokeOff}
        onWidthChange={(widthPx) =>
          onChange({
            ...effects,
            stroke: strokeOff
              ? { color: stroke.color, widthPx }
              : { ...stroke, widthPx },
          })
        }
        onColorChange={(color) =>
          onChange({
            ...effects,
            stroke: strokeOff
              ? { color, widthPx: DEFAULT_STROKE_WIDTH_PX }
              : { ...stroke, color },
          })
        }
      />
    </section>
  );
}

// figma 2015:249496 — section headers use text-[14px] SemiBold, same as
// 변형/윤곽선/레터박스/불투명도/그림자 labels in the 배경 tab spec.
function Header({ label }: { label: string }) {
  return (
    <h3 className="mb-2.5 text-[14px] font-semibold leading-[1.4] tracking-[-0.35px] text-grayscale-800">
      {label}
    </h3>
  );
}
