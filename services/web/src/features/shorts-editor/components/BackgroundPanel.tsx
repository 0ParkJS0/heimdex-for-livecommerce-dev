"use client";

// figma: 2015:249496 (배경 섹션 — redesigned)
//
// Background tab content rendered as the RightPanel's backgroundTab. This
// used to be a self-contained mock with its own state — none of the
// controls were wired to the editor reducer, which is why "the background
// section looked unchanged" after we redesigned BackgroundEditingBody:
// the user always saw V1's local-state UI, never V2's. This file is now a
// thin wrapper that drives the editor reducer through the same V2
// primitives the OverlayPanel uses (ActionBar + BackgroundEditingBody).
//
// 2026-05-22 — Figma 2015:249496 adds the letterbox stepper row between
// ActionBar and BackgroundEditingBody. Shows '상단 / 하단' px inputs
// only when a letterbox exists in state.
//
// 2026-05-24 — selection-based routing model (operator request).
// The existing canvas-align / layer-order / 윤곽선 controls now route
// to whichever element (video / letterbox / overlay) the operator
// just clicked in the preview canvas. Controls dim when no element
// is selected, or when the selected element doesn't expose that
// control (e.g. letterbox has no x/y to align).

import { useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import { ActionBar } from "./OverlayPanel/ActionBar";
import { BackgroundEditingBody } from "./OverlayPanel";
import { BackgroundToolbar } from "./OverlayPanel/BackgroundToolbar";
import { BorderControl } from "./OverlayPanel/BorderControl";
import { DEFAULT_STROKE_WIDTH_PX } from "./OverlayPanel/EffectsSection";
import { ShadowControl } from "./OverlayPanel/ShadowControl";
import { t } from "../lib/i18n/strings";
import { ColorPalettePopover } from "./primitives/ColorPalettePopover";
import { ColorPalettePortal } from "./primitives/ColorPalettePortal";
import { createDefaultBackgroundOverlay } from "../lib/overlay-defaults";
import {
  computeCanvasAlignTarget,
  type CanvasAlignAxis,
  type CanvasAlignPosition,
} from "../lib/canvas-align";
import type {
  EditorBackgroundOverlay,
  EditorOverlay,
  EffectsProps,
} from "../lib/overlay-types";
import type { EditorState, LayerOrderId } from "../lib/types";

// Letterbox is stored as a percentage of canvas height (0–49 each
// edge). The stepper UI mirrors Figma's "25px" presentation, so we
// convert to px-of-720-output at the display layer. 100 % = 720 px →
// 1 % = 7.2 px. The stepper steps by 5 px (≈ 0.69 %) per chevron click
// because 1-px increments feel sluggish on a 100-px bar.
const PCT_PER_PX = 1 / 7.2;
const LETTERBOX_PX_STEP = 5;
const LETTERBOX_MAX_PCT = 50;
const pctToPx = (pct: number) => Math.round(pct * 7.2);

// Outline default when the operator picks a colour from a previously-OFF
// state. Matches the letterbox borderWidth default and overlay stroke
// default so the affordance is consistent across slots.
const DEFAULT_OUTLINE_WIDTH_PX = 5;
const OUTLINE_OFF_COLOR = "#FF0000";

interface BackgroundPanelProps {
  state: EditorState;
  onAddSolidBackground: (fillColor?: string) => void;
  onAddImageBackground: (imageUrl: string) => void;
  onUpdateOverlay: (id: string, updates: Partial<EditorOverlay>) => void;
  onReorderOverlay: (
    id: string,
    direction: "front" | "back" | "forward" | "backward",
  ) => void;
  // Dispatches the unified REORDER_LAYER action so z-order in the preview
  // reflects the operator's intent for both overlays and letterbox.
  onReorderLayer: (
    layer: LayerOrderId,
    direction: "front" | "back" | "forward" | "backward",
  ) => void;
  // Item 3 — letterbox is owned by the editor reducer (D4 = B), not
  // by the overlay array, so the panel needs explicit wiring.
  onSetLetterbox: (letterbox: EditorState["letterbox"]) => void;
  // Snap the video layer to canvas extremes (left/center/right ·
  // top/middle/bottom). x and y are normalized anchors written into
  // state.videoTransform — used when the operator selects the host
  // video and activates a canvas-align option.
  onUpdateVideoPosition: (x: number, y: number) => void;
  // Outline (윤곽선) around the video frame. ``null`` clears it.
  onSetVideoOutline: (
    outline: { color: string; widthPx: number } | null,
  ) => void;
  // Drop shadow around the video frame. ``null`` clears it. Mirrors
  // the overlay ShadowProps shape so the same ShadowControl primitive
  // drives the row.
  onSetVideoShadow: (
    shadow: {
      color: string;
      offsetX: number;
      offsetY: number;
      blurPx: number;
      spreadPx: number;
    } | null,
  ) => void;
}

export function BackgroundPanel({
  state,
  onAddSolidBackground,
  onAddImageBackground,
  onUpdateOverlay,
  onReorderOverlay,
  onReorderLayer,
  onSetLetterbox,
  onUpdateVideoPosition,
  onSetVideoOutline,
  onSetVideoShadow,
}: BackgroundPanelProps) {
  void onAddSolidBackground;
  // Resolve the currently selected background overlay; fall back to a
  // stable default so the controls always render and the user sees the
  // section layout even before adding their first background.
  const selectedOverlay = state.selectedOverlayId
    ? state.overlays.find((o) => o.id === state.selectedOverlayId) ?? null
    : null;
  const selectedBg =
    selectedOverlay && selectedOverlay.kind === "background"
      ? (selectedOverlay as EditorBackgroundOverlay)
      : null;

  const defaultBg = useMemo(
    () => createDefaultBackgroundOverlay({ startMs: 0 }),
    [],
  );

  // Selection routing — exactly one of these is "true" at a time per the
  // reducer's mutex semantics (SELECT_VIDEO / SELECT_LETTERBOX clear
  // overlay; SELECT_OVERLAY clears video + letterbox). When none is
  // active the toolbar + outline row dim and no-op.
  const isVideoSelected = state.selectedVideo;
  const isLetterboxSelected = state.selectedLetterbox && state.letterbox != null;
  const isOverlaySelected = selectedBg != null;
  const hasAnySelection = isVideoSelected || isLetterboxSelected || isOverlaySelected;

  // --- Canvas-align routing ------------------------------------------
  const handleCanvasAlign = (
    axis: CanvasAlignAxis,
    position: CanvasAlignPosition,
  ) => {
    if (isVideoSelected) {
      // Snap the video layer to a canvas extreme. The video element is
      // scaled around its centre (see PreviewPanel's transform=
      // ``scale(s) translate((x-0.5)*100%, (y-0.5)*100%)``) so an
      // anchor of 0.5/0.5 keeps the centred default. For "start", the
      // video's leading edge sits at the canvas leading edge → centre
      // at scale/2. For "end", centre at 1 - scale/2.
      const { scale, x, y } = state.videoTransform;
      const target =
        position === "center"
          ? 0.5
          : position === "start"
            ? scale / 2
            : 1 - scale / 2;
      if (axis === "x") onUpdateVideoPosition(target, y);
      else onUpdateVideoPosition(x, target);
      return;
    }
    if (isOverlaySelected && selectedBg) {
      // Existing overlay canvas-align path — measure the rendered
      // overlay against the canvas (lib/canvas-align resolves anchor
      // correction) and write the new normalized x/y.
      const next = computeCanvasAlignTarget(selectedBg.id, axis, position);
      onUpdateOverlay(selectedBg.id, {
        transform: { ...selectedBg.transform, [axis]: next },
      });
      return;
    }
    // Letterbox + nothing selected → no-op. The popover's
    // ``canvasAlignDisabled`` already prevents the operator from
    // reaching here through the UI, but guard the dispatch anyway in
    // case a keyboard shortcut wires up later.
  };

  // Letterbox doesn't expose x/y — disable the popover when it's the
  // active selection, OR when nothing is selected.
  const canvasAlignDisabled = isLetterboxSelected || !hasAnySelection;

  // --- Layer-order routing -------------------------------------------
  const handleReorder = (
    direction: "front" | "back" | "forward" | "backward",
  ) => {
    if (isVideoSelected) {
      onReorderLayer({ kind: "video" }, direction);
      return;
    }
    if (isLetterboxSelected) {
      onReorderLayer({ kind: "letterbox" }, direction);
      return;
    }
    if (isOverlaySelected && selectedBg) {
      // Existing dual dispatch: keeps per-overlay layerIndex in sync
      // with the unified layer-order stack (operator intent
      // '레이어 순서 바꿀 수 있어야 한다').
      onReorderOverlay(selectedBg.id, direction);
      onReorderLayer({ kind: "overlay", id: selectedBg.id }, direction);
    }
  };

  const layerOrderDisabled = !hasAnySelection;

  // --- Outline (윤곽선) row routing ---------------------------------
  // The outline row replaces what was the overlay-only StrokeBlock. It
  // surfaces different fields per selection slot:
  //   * selectedVideo      → state.videoTransform.outline
  //   * selectedLetterbox  → state.letterbox.borderColor / borderWidthPx
  //   * selectedOverlayId  → overlay.effects.stroke (delegates back to
  //                          the StrokeBlock-style flow on the overlay)
  //   * nothing selected   → disabled (BorderControl renders w/ placeholder)
  const outlineSlot = (() => {
    if (isVideoSelected) {
      const outline = state.videoTransform.outline ?? null;
      const off = outline === null;
      const color = outline?.color ?? OUTLINE_OFF_COLOR;
      const widthPx = outline?.widthPx ?? 0;
      // Shadow row materialises a default on first mount so the
      // sliders immediately show numbers — same UX the overlay
      // EffectsSection uses (DEFAULT_SHADOW: black, +5/+5 offset).
      // Until the operator dials a value, ``onSetVideoShadow`` is
      // dispatched with that default so any later edit only patches
      // the existing object.
      const shadow = state.videoTransform.shadow ?? {
        color: "#000000",
        offsetX: 5,
        offsetY: 5,
        blurPx: 0,
        spreadPx: 0,
      };
      return (
        <>
          <section>
            <Header label={t.effects.stroke} />
            <BorderControl
              width={widthPx}
              color={color}
              strokeIsOff={off}
              onWidthChange={(nextWidth) => {
                if (off) return;
                onSetVideoOutline({ color, widthPx: nextWidth });
              }}
              onColorChange={(nextColor) => {
                onSetVideoOutline({
                  color: nextColor.toUpperCase(),
                  widthPx: off ? DEFAULT_OUTLINE_WIDTH_PX : widthPx,
                });
              }}
            />
          </section>
          <section>
            <Header label={t.effects.shadow} />
            <ShadowControl
              offsetX={shadow.offsetX}
              offsetY={shadow.offsetY}
              spread={shadow.spreadPx}
              blur={shadow.blurPx}
              color={shadow.color}
              onChange={(next) =>
                onSetVideoShadow({
                  color: next.color,
                  offsetX: next.offsetX,
                  offsetY: next.offsetY,
                  blurPx: next.blur,
                  spreadPx: next.spread,
                })
              }
            />
          </section>
        </>
      );
    }
    if (isLetterboxSelected && state.letterbox) {
      const lb = state.letterbox;
      const off = lb.borderColor === null;
      const color = lb.borderColor ?? OUTLINE_OFF_COLOR;
      const widthPx = lb.borderWidthPx ?? 0;
      return (
        <section>
          <Header label={t.effects.stroke} />
          <BorderControl
            width={widthPx}
            color={color}
            strokeIsOff={off}
            onWidthChange={(nextWidth) => {
              if (off) return;
              onSetLetterbox({ ...lb, borderWidthPx: nextWidth });
            }}
            onColorChange={(nextColor) => {
              onSetLetterbox({
                ...lb,
                borderColor: nextColor.toUpperCase(),
                borderWidthPx: off ? DEFAULT_OUTLINE_WIDTH_PX : widthPx,
              });
            }}
          />
        </section>
      );
    }
    if (isOverlaySelected && selectedBg) {
      // Overlay stroke path — same shape EffectsSection.StrokeBlock
      // uses, just inlined here so the panel owns the disabled state.
      const stroke = selectedBg.effects.stroke;
      const off = stroke === null;
      const color = stroke?.color ?? OUTLINE_OFF_COLOR;
      const widthPx = stroke?.widthPx ?? 0;
      return (
        <section>
          <Header label={t.effects.stroke} />
          <BorderControl
            width={widthPx}
            color={color}
            strokeIsOff={off}
            onWidthChange={(nextWidth) => {
              if (off) return;
              const nextEffects: EffectsProps = {
                ...selectedBg.effects,
                stroke: { color, widthPx: nextWidth },
              };
              onUpdateOverlay(selectedBg.id, { effects: nextEffects });
            }}
            onColorChange={(nextColor) => {
              const nextEffects: EffectsProps = {
                ...selectedBg.effects,
                stroke: off
                  ? { color: nextColor, widthPx: DEFAULT_STROKE_WIDTH_PX }
                  : { color: nextColor, widthPx },
              };
              onUpdateOverlay(selectedBg.id, { effects: nextEffects });
            }}
          />
        </section>
      );
    }
    // Nothing selected — render the dimmed placeholder so the section
    // layout stays consistent.
    return (
      <section className="pointer-events-none opacity-40">
        <Header label={t.effects.stroke} />
        <BorderControl
          width={0}
          color={OUTLINE_OFF_COLOR}
          strokeIsOff
          disabled
          onWidthChange={() => {}}
          onColorChange={() => {}}
        />
      </section>
    );
  })();

  const handleLetterboxStep = (
    edge: "top" | "bottom",
    direction: 1 | -1,
  ) => {
    if (!state.letterbox) return;
    const currentPct =
      edge === "top"
        ? state.letterbox.topHeightPct
        : state.letterbox.bottomHeightPct;
    const nextPct = Math.max(
      0,
      Math.min(
        LETTERBOX_MAX_PCT,
        currentPct + direction * LETTERBOX_PX_STEP * PCT_PER_PX,
      ),
    );
    onSetLetterbox(
      edge === "top"
        ? { ...state.letterbox, topHeightPct: nextPct }
        : { ...state.letterbox, bottomHeightPct: nextPct },
    );
  };

  // figma 2026:249502 — letterbox section: header + one flex row with
  // 상단 stepper, 하단 stepper, and color swatch aligned to bottom.
  // Injected into BackgroundEditingBody's betweenToolbarAndTransform slot
  // so it appears AFTER the toolbar row and BEFORE 변형+윤곽선, matching
  // the Figma 2015:249496 layout exactly.
  const letterboxSection = state.letterbox ? (
    <div className="flex flex-col gap-[10px]">
      <p className="text-[14px] font-semibold leading-[1.4] tracking-[-0.35px] text-grayscale-800">
        레터박스
      </p>
      {/* figma 2026:249529 — steppers + swatch in one items-end row */}
      <div className="flex items-end gap-[10px]">
        <LetterboxStepper
          label="상단"
          valuePx={pctToPx(state.letterbox.topHeightPct)}
          onIncrement={() => handleLetterboxStep("top", 1)}
          onDecrement={() => handleLetterboxStep("top", -1)}
        />
        <LetterboxStepper
          label="하단"
          valuePx={pctToPx(state.letterbox.bottomHeightPct)}
          onIncrement={() => handleLetterboxStep("bottom", 1)}
          onDecrement={() => handleLetterboxStep("bottom", -1)}
        />
        {/* figma 2045:407005 — color swatch inline with steppers.
            Kept here so the operator can recolour the bar fill from the
            letterbox row regardless of which element they have
            selected — the selection-routed 윤곽선 row only handles the
            BORDER colour, not the fill. */}
        <LetterboxColorSwatch
          borderColor={state.letterbox.borderColor}
          fillColor={state.letterbox.fillColor}
          onChange={(borderColor, borderWidthPx) => {
            if (!state.letterbox) return;
            onSetLetterbox({ ...state.letterbox, borderColor, borderWidthPx });
          }}
        />
      </div>
    </div>
  ) : undefined;

  return (
    // figma 2015:249496 — outer container p-[20px] gap-[16px]
    <div className="flex flex-col gap-4 p-5">
      <ActionBar
        kind="background"
        onAddText={() => {}}
        onAddImage={onAddImageBackground}
        letterbox={state.letterbox}
        onSetLetterbox={onSetLetterbox}
      />
      <BackgroundEditingBody
        overlay={selectedBg ?? defaultBg}
        onUpdate={(updates) => {
          if (selectedBg) onUpdateOverlay(selectedBg.id, updates);
        }}
        toolbar={
          <BackgroundToolbar
            onCanvasAlign={handleCanvasAlign}
            canvasAlignDisabled={canvasAlignDisabled}
            onReorder={handleReorder}
            layerOrderDisabled={layerOrderDisabled}
          />
        }
        strokeBlock={outlineSlot}
        isPlaceholder={!hasAnySelection && !state.letterbox}
        betweenToolbarAndTransform={
          letterboxSection ? (
            <div className="flex flex-col gap-4">{letterboxSection}</div>
          ) : undefined
        }
      />
    </div>
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

// figma 2045:407005 — inline colour swatch for the letterbox section.
// Sits in the same items-end flex row as the 상단/하단 steppers.
// Clicking opens the palette to change the letterbox fill / border colour.
// Right-click removes the border colour entirely (preserves fill).
// No separate 윤곽선 header or 굵기 label — those belong to the overlay
// stroke section, not the letterbox bar.
function LetterboxColorSwatch({
  borderColor,
  fillColor,
  onChange,
}: {
  borderColor: string | null;
  fillColor: string;
  onChange: (color: string | null, widthPx: number) => void;
}) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const swatchRef = useRef<HTMLButtonElement>(null);

  // Display the fill colour as the swatch — the letterbox bar colour
  // is what the operator visually picks here. borderColor is passed
  // through onChange for compat with the reducer shape.
  const displayColor = fillColor ?? borderColor ?? "#000000";

  return (
    // figma 2045:407005 — h-[40px] wrapper aligns with stepper height
    <div className="flex h-10 items-center">
      <div className="relative">
        <button
          ref={swatchRef}
          type="button"
          onClick={() => setPaletteOpen((v) => !v)}
          onContextMenu={(e) => {
            e.preventDefault();
            onChange(null, 5);
          }}
          aria-label={`레터박스 색 ${displayColor} — 우클릭 시 테두리 제거`}
          // figma 2045:407005 — size-[40px] border-[0.909px] rounded-[10px] p-[5px]
          className="flex h-10 w-10 items-center justify-center rounded-[10px] border-[0.909px] border-grayscale-300 p-[5px]"
        >
          <div
            className="h-full w-full flex-1 rounded-[6px]"
            style={{ backgroundColor: displayColor }}
          />
        </button>
        {paletteOpen && (
          <ColorPalettePortal
            anchorRef={swatchRef}
            onClose={() => setPaletteOpen(false)}
          >
            <ColorPalettePopover
              color={displayColor}
              onChange={(next) => {
                onChange(next.toUpperCase(), 5);
                setPaletteOpen(false);
              }}
              onClose={() => setPaletteOpen(false)}
              showOpacity={false}
            />
          </ColorPalettePortal>
        )}
      </div>
    </div>
  );
}

// figma 2026:249518 (상단), 2026:324269 (하단) — column with a 12-px
// Medium label above a 40-px-tall input row. The input itself is a
// border-1 #C4C5D4 rounded-10 box (px-8 py-4) showing the current
// value plus a 16-px chevron-up/chevron-down stack on the right.
function LetterboxStepper({
  label,
  valuePx,
  onIncrement,
  onDecrement,
}: {
  label: string;
  valuePx: number;
  onIncrement: () => void;
  onDecrement: () => void;
}) {
  return (
    // figma 2026:249518/2026:324269 — gap-[4px] between label and input box
    <div className="flex flex-col items-start gap-1">
      <p className="text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-grayscale-500">
        {label}
      </p>
      {/* figma 2026:249520 — h-[40px] wrapper, input box px-[8px] py-[4px] gap-[10px] rounded-[10px] */}
      <div className="flex h-10 items-center">
        <div className="flex min-w-[56px] items-center gap-[10px] rounded-[10px] border border-grayscale-300 bg-white px-[8px] py-[4px]">
          <p className="text-[14px] font-medium leading-[1.4] tracking-[-0.35px] text-grayscale-800" style={{ fontVariantNumeric: "tabular-nums" }}>
            {valuePx}px
          </p>
          {/* figma 2026:324250 — 16px chevron stack */}
          <div className="flex w-4 flex-col items-start">
            <button
              type="button"
              aria-label={`${label} 높이 늘리기`}
              onClick={onIncrement}
              className="text-grayscale-700 hover:text-grayscale-900"
            >
              <ChevronUp className="h-4 w-4" />
            </button>
            <button
              type="button"
              aria-label={`${label} 높이 줄이기`}
              onClick={onDecrement}
              className="text-grayscale-700 hover:text-grayscale-900"
            >
              <ChevronDown className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
