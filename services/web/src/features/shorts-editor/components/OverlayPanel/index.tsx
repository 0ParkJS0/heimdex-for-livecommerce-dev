"use client";

import React, { useEffect, useMemo } from "react";

import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { FontDropdown } from "../primitives/FontDropdown";
import { ActionBar } from "./ActionBar";
import { BackgroundToolbar } from "./BackgroundToolbar";
import { EffectsSection, StrokeBlock } from "./EffectsSection";
import { TextToolbar } from "./TextToolbar";
import { TransformSection } from "./TransformSection";
import { useOverlaySelection } from "../../hooks/useOverlaySelection";
import { usePresets } from "../../hooks/usePresets";
import { t } from "../../lib/i18n/strings";
import {
  createDefaultBackgroundOverlay,
  createDefaultTextOverlay,
} from "../../lib/overlay-defaults";
import { runOneTimePresetMigration } from "../../lib/preset-migration";
import type {
  EditorBackgroundOverlay,
  EditorOverlay,
  EditorTextOverlay,
  EffectsProps,
  TransformProps,
} from "../../lib/overlay-types";
import type { EditorState, SubtitleStyle } from "../../lib/types";

import { FONT_OPTIONS } from "../../constants";

interface OverlayPanelProps {
  state: EditorState;
  onAddTextOverlay: () => void;
  // figma 1602:40004 (배경 섹션) — 단색 배경 추가 버튼은 색상 팔레트
  // 팝업을 띄우고, 선택한 색이 신규 background overlay 의 fillColor 로
  // 주입된다. 인자가 없으면 기본 색이 적용된다.
  onAddBackgroundOverlay: (fillColor?: string) => void;
  // "Insert image" — seeds a new background overlay with the data URL
  // the file picker returned, painted on top of a transparent fill.
  onAddImageBackgroundOverlay: (imageUrl: string) => void;
  onUpdateOverlay: (id: string, updates: Partial<EditorOverlay>) => void;
  onRemoveOverlay: (id: string) => void;
  onSelectOverlay: (id: string | null) => void;
  onReorderOverlay: (
    id: string,
    direction: "front" | "back" | "forward" | "backward",
  ) => void;
  // When a V1 subtitle is selected in the left panel, the right panel
  // shows its style and dispatches global style updates to all subtitles.
  onUpdateAllSubtitleStyles?: (updates: Partial<SubtitleStyle>) => void;
}

/**
 * V2 overlay panel — replaces TextOverlayPanel when the feature flag is on.
 *
 * Tab state is local to the panel: tabs reflect what the user wants to be
 * editing, NOT the kind of the selected overlay. If the user has a text
 * overlay selected and switches to the Background tab, the panel switches
 * to a "you have no background selected" empty state and shows the bg
 * actions; the text overlay remains in state.
 *
 * When the user clicks "+ 텍스트 추가" or "+ 단색 배경 추가" we add an overlay
 * of the matching kind, which the reducer auto-selects, and the panel
 * fills with its fields.
 */
export function OverlayPanel({
  state,
  onAddTextOverlay,
  onAddBackgroundOverlay,
  onAddImageBackgroundOverlay,
  onUpdateOverlay,
  onRemoveOverlay,
  onSelectOverlay,
  onReorderOverlay,
  onUpdateAllSubtitleStyles,
}: OverlayPanelProps) {
  void onAddBackgroundOverlay;
  void onAddImageBackgroundOverlay;
  void onReorderOverlay;
  const { selected } = useOverlaySelection(state);
  const { getAccessToken } = useAuth();

  const selectedTextOverlay =
    selected && selected.kind === "text"
      ? (selected as EditorTextOverlay)
      : null;

  // When a V1 subtitle is selected (left panel click) and no V2 text
  // overlay is selected, show that subtitle's style in the controls.
  // Style edits dispatch UPDATE_ALL_SUBTITLE_STYLES so every subtitle
  // gets the same look (operator-confirmed: 전 구간 자막에 동일 스타일).
  const selectedSubtitle =
    state.selectedSubtitleIndex != null &&
    state.selectedSubtitleIndex < state.subtitles.length
      ? state.subtitles[state.selectedSubtitleIndex]
      : null;

  const showSubtitleStyle =
    selectedSubtitle != null && selectedTextOverlay == null;

  // Build a synthetic EditorTextOverlay from the subtitle's style so
  // TextEditingBody can display its values without a dedicated UI.
  const subtitleAsOverlay = useMemo(() => {
    if (!selectedSubtitle) return null;
    const base = createDefaultTextOverlay({ startMs: 0 });
    return {
      ...base,
      fontFamily: selectedSubtitle.style.fontFamily as typeof base.fontFamily,
      fontSizePx: selectedSubtitle.style.fontSizePx,
      fontColor: selectedSubtitle.style.fontColor,
      fontWeight: selectedSubtitle.style.fontWeight,
      text: selectedSubtitle.text,
    };
  }, [selectedSubtitle]);

  const defaultTextOverlay = useMemo(
    () => createDefaultTextOverlay({ startMs: 0 }),
    [],
  );

  const presetsApi = usePresets({
    kind: "text",
    getToken: getAccessToken,
    enabled: true,
  });

  useEffect(() => {
    let cancelled = false;
    void runOneTimePresetMigration(getAccessToken).then((result) => {
      if (!cancelled && result.migrated > 0) {
        void presetsApi.reload();
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getAccessToken]);

  // Resolve which overlay to display and which handler to call.
  const displayOverlay = selectedTextOverlay ?? subtitleAsOverlay ?? defaultTextOverlay;
  const isPlaceholder = selectedTextOverlay == null && !showSubtitleStyle;

  const handleUpdate = (updates: Partial<EditorTextOverlay>) => {
    if (selectedTextOverlay) {
      onUpdateOverlay(selectedTextOverlay.id, updates);
    } else if (showSubtitleStyle && onUpdateAllSubtitleStyles) {
      // Map EditorTextOverlay fields back to SubtitleStyle fields.
      const styleUpdates: Partial<SubtitleStyle> = {};
      if ("fontFamily" in updates && updates.fontFamily != null)
        styleUpdates.fontFamily = updates.fontFamily;
      if ("fontSizePx" in updates && updates.fontSizePx != null)
        styleUpdates.fontSizePx = updates.fontSizePx;
      if ("fontColor" in updates && updates.fontColor != null)
        styleUpdates.fontColor = updates.fontColor;
      if ("fontWeight" in updates && updates.fontWeight != null)
        styleUpdates.fontWeight = updates.fontWeight;
      if (Object.keys(styleUpdates).length > 0) {
        onUpdateAllSubtitleStyles(styleUpdates);
      }
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="scrollbar-hidden flex-1 space-y-4 overflow-y-auto">
        <ActionBar
          kind="text"
          onAddText={onAddTextOverlay}
          onAddBackground={() => {}}
          onAddImage={() => {}}
        />

        <TextEditingBody
          overlay={displayOverlay}
          onUpdate={handleUpdate}
          isPlaceholder={isPlaceholder}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Text editing body
// ---------------------------------------------------------------------------

function TextEditingBody({
  overlay,
  onUpdate,
  isPlaceholder = false,
}: {
  overlay: EditorTextOverlay;
  onUpdate: (updates: Partial<EditorTextOverlay>) => void;
  // figma 1663:45752 — when no overlay is selected the controls still
  // render with default values; isPlaceholder dims the surface so it's
  // visually clear inputs won't persist until an overlay is added.
  isPlaceholder?: boolean;
}) {
  return (
    <div className={cn("space-y-4", isPlaceholder && "opacity-60")}>
      {/* figma 2031:328975 — the right panel no longer carries a
          content textarea. Host subtitles are edited inline in the
          left wrapper (Figma 2031:329131) and operator-added text
          overlays are edited by double-clicking the canvas overlay
          (Figma 2031:328972). The right panel keeps style controls
          only. */}

      {/* Top divider — same style as the dividers between 윤곽선/
          불투명도 and 불투명도/그림자 below. Separates the ActionBar
          '텍스트 추가' button (rendered by the OverlayPanel parent)
          from the style controls in this body. */}
      <hr className="border-grayscale-100" />

      <div className="grid grid-cols-[1fr_120px] gap-2">
        <FontDropdown
          value={overlay.fontFamily}
          options={FONT_OPTIONS}
          onChange={(v) =>
            onUpdate({ fontFamily: v as EditorTextOverlay["fontFamily"] })
          }
          ariaLabel={t.text.fontFamily}
        />
        <NumericFieldWithUnit
          value={overlay.fontSizePx}
          unit="pt"
          min={8}
          max={200}
          onChange={(v) => onUpdate({ fontSizePx: v })}
        />
      </div>

      <TextToolbar overlay={overlay} onChange={onUpdate} />

      <hr className="border-grayscale-100" />

      {/* figma 1663:45821 — 변형 + 윤곽선 nudged into a 2-col row */}
      <div className="grid grid-cols-2 gap-x-3.5 gap-y-2">
        <TransformSection
          overlay={overlay}
          onChange={(transform: TransformProps) => onUpdate({ transform })}
        />
        <StrokeBlock
          key={`stroke-${overlay.id}`}
          effects={overlay.effects}
          onChange={(effects: EffectsProps) => onUpdate({ effects })}
        />
      </div>

      <hr className="border-grayscale-100" />

      {/* ``key={overlay.id}`` remounts EffectsSection whenever the
          operator switches to a different overlay. Without the key,
          the section's mount-time useEffect (which materializes
          DEFAULT_STROKE / DEFAULT_SHADOW into state) fires only once
          for the first overlay; later overlays keep their null
          effects and the renderer applies no CSS, so the operator
          drags shadow sliders and sees no visual change. */}
      <EffectsSection
        key={overlay.id}
        effects={overlay.effects}
        onChange={(effects: EffectsProps) => onUpdate({ effects })}
        hideStroke
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Background editing body
// ---------------------------------------------------------------------------

// figma 2015:249496 — Background editing body.
// Layout order (top to bottom):
//   hr → toolbar (align + layer-order) → hr → [betweenToolbarAndTransform
//   slot: letterbox section rendered by BackgroundPanel] → 변형 + 윤곽선
//   (2-col grid) → hr → 불투명도 + 그림자
//
// betweenToolbarAndTransform: optional content (e.g. letterbox section)
// inserted between the toolbar divider and the 변형+윤곽선 grid.
// When present it is preceded by its own divider so sections stay
// visually separated.
//
// 2026-05-24 — selection-based routing model. The body no longer
// derives the toolbar / stroke callbacks from ``overlay`` alone; the
// caller (BackgroundPanel) passes selection-aware callbacks that
// route based on which element is currently selected (video /
// letterbox / overlay). ``toolbar`` and ``strokeBlock`` are slots so
// the caller controls disable / no-op semantics per slot.
export function BackgroundEditingBody({
  overlay,
  onUpdate,
  toolbar,
  isPlaceholder = false,
  betweenToolbarAndTransform,
  strokeBlock,
}: {
  overlay: EditorBackgroundOverlay;
  onUpdate: (updates: Partial<EditorBackgroundOverlay>) => void;
  // Toolbar slot — selection-aware caller renders a BackgroundToolbar
  // with the right callbacks. Required so the body never falls back
  // to a stale overlay-only toolbar.
  toolbar: React.ReactNode;
  isPlaceholder?: boolean;
  // figma 2015:249496 — slot for the letterbox section (rendered by
  // BackgroundPanel). Sits between the toolbar row and the 변형+윤곽선 grid.
  betweenToolbarAndTransform?: React.ReactNode;
  // 윤곽선 (stroke / border) slot — selection-aware caller renders a
  // StrokeBlock that targets the currently-selected element (overlay
  // effects.stroke / letterbox borderColor / videoTransform.outline).
  // When undefined, falls back to the overlay's effects.stroke so the
  // existing overlay-edit path stays intact.
  strokeBlock?: React.ReactNode;
}) {
  return (
    <div className={cn("space-y-4", isPlaceholder && "opacity-60")}>
      {/* figma 2015:249496 — divider between ActionBar and toolbar row */}
      <hr className="border-grayscale-100" />

      {/* figma 2015:246595 — align + layer-order toolbar, right-aligned */}
      {toolbar}

      {/* figma 2015:246614 — divider between toolbar and next section */}
      <hr className="border-grayscale-100" />

      {/* Letterbox section (injected by BackgroundPanel when letterbox exists) */}
      {betweenToolbarAndTransform && (
        <>
          {betweenToolbarAndTransform}
          <hr className="border-grayscale-100" />
        </>
      )}

      {/* figma 2015:249496 — 변형 + 윤곽선 in a 2-col grid.
          크기 (W/H) is rendered first inside TransformSection for bg overlays
          (Figma order: 크기 → 위치 → 회전). */}
      <div className="grid grid-cols-2 gap-x-3.5 gap-y-2">
        <TransformSection
          overlay={overlay}
          onChange={(transform: TransformProps) => onUpdate({ transform })}
        />
        {strokeBlock ?? (
          <StrokeBlock
            key={`stroke-${overlay.id}`}
            effects={overlay.effects}
            onChange={(effects: EffectsProps) => onUpdate({ effects })}
          />
        )}
      </div>

      <hr className="border-grayscale-100" />

      <EffectsSection
        key={overlay.id}
        effects={overlay.effects}
        onChange={(effects: EffectsProps) => onUpdate({ effects })}
        hideStroke
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Misc
// ---------------------------------------------------------------------------

function NumericFieldWithUnit({
  value,
  unit,
  min,
  max,
  onChange,
}: {
  value: number;
  unit: string;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center rounded-lg border border-grayscale-200 bg-white">
      <button
        type="button"
        onClick={() => onChange(Math.max(min, value - 1))}
        className="flex h-9 w-7 items-center justify-center text-grayscale-500 hover:text-grayscale-800"
      >
        −
      </button>
      <input
        type="text"
        inputMode="numeric"
        value={String(value)}
        onChange={(e) => {
          const raw = Number(e.target.value);
          if (!Number.isFinite(raw)) return;
          onChange(Math.min(max, Math.max(min, raw)));
        }}
        className="w-full min-w-0 border-x border-transparent bg-transparent py-1 text-center text-sm text-grayscale-800 focus:outline-none"
      />
      <span className="px-1 text-[10px] text-grayscale-400">{unit}</span>
      <button
        type="button"
        onClick={() => onChange(Math.min(max, value + 1))}
        className="flex h-9 w-7 items-center justify-center text-grayscale-500 hover:text-grayscale-800"
      >
        +
      </button>
    </div>
  );
}

// OverlaySelectorRow (the every-overlay ``T: ...`` chip strip) was
// removed entirely on 2026-05-18 — it filled the right wrapper once
// auto-subtitle wiring added many text overlays. Function definition
// dropped to make sure nothing accidentally re-mounts it.
