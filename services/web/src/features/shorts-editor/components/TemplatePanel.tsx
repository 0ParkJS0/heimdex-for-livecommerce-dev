"use client";

// figma: 1602:41198  (cache: .figma-cache/screenshots/1607-65302_reference.png)
// node-name: 템플릿 탭 (right-panel "템플릿" tab content)
// spec: action row (dropdown + "적용하기") + 2-col card grid (9:16, checker bg,
//   centered placeholder text, top-right rounded-square check indicator).
// Save trigger lives in EditorHeader's TemplateSaveMenu (the standalone
// "+" affordance was removed); the empty state mirrors that entry point.

import { useId, useState } from "react";

import { Check, Trash2 } from "lucide-react";

import { resolveFontFamily } from "@/lib/fonts";
import { cn } from "@/lib/utils";
import type { WirePreset } from "../lib/overlay-types";
import type { StarterTemplate } from "../lib/starter-templates";

interface TemplatePanelProps {
  presets: WirePreset[];
  // Hardcoded "ready-made caption" templates rendered above the user
  // presets section. Clicking one inserts a brand new text overlay at
  // the playhead with the template's full style payload; the user-
  // preset apply-to-selected flow below is unaffected.
  starterTemplates?: readonly StarterTemplate[];
  onApplyStarter?: (template: StarterTemplate) => void;
  isLoading?: boolean;
  error?: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onApply: (preset: WirePreset) => void;
  onOpenSaveDialog: () => void;
  onDelete?: (preset: WirePreset) => void;
}

export function TemplatePanel({
  presets,
  starterTemplates = [],
  onApplyStarter,
  isLoading = false,
  error = null,
  selectedId,
  onSelect,
  onApply,
  onOpenSaveDialog,
  onDelete,
}: TemplatePanelProps) {
  const selected = presets.find((p) => p.id === selectedId) ?? null;

  return (
    <div className="flex h-full flex-col gap-4 rounded-dialog bg-white p-5">
      <ActionRow
        selected={selected}
        selectedName={selected?.name ?? null}
        disabled={!selected}
        onApply={() => {
          if (selected) onApply(selected);
        }}
        onDelete={
          onDelete
            ? () => {
                if (selected) onDelete(selected);
              }
            : undefined
        }
        presets={presets}
        onPickPreset={(id) => onSelect(id)}
        starterTemplates={starterTemplates}
        onPickStarter={onApplyStarter}
      />

      {/* Q9 — '저장된 템플릿' subsection + '현재 스타일 저장' empty
          state CTA are removed; saving lives exclusively in the GNB
          템플릿 저장 popup. Saved presets prepend the hardcoded starter
          cards in a single unified grid, recent-added first per the
          Q9 spec. */}
      <div className="flex-1 space-y-4 overflow-y-auto">
        {isLoading && (
          <p className="text-xs text-grayscale-400">템플릿 불러오는 중…</p>
        )}
        <div className="grid grid-cols-2 gap-4">
          {sortPresetsRecentFirst(presets).map((preset) => (
            <TemplateCard
              key={preset.id}
              preset={preset}
              selected={preset.id === selectedId}
              onSelect={() => onSelect(preset.id)}
              onDelete={onDelete ? () => onDelete(preset) : undefined}
            />
          ))}
          {starterTemplates.length > 0 &&
            onApplyStarter &&
            starterTemplates.map((template) => (
              <StarterTemplateCard
                key={template.id}
                template={template}
                onApply={() => onApplyStarter(template)}
              />
            ))}
        </div>
        {error && <p className="mt-2 text-[11px] text-red-h-500">{error}</p>}
      </div>
    </div>
  );
}

// Q9 — saved templates render newest-first so a just-saved preset
// pops to the top of the grid above the hardcoded starter cards.
// Falls back to original list order when ``created_at`` parses to NaN.
function sortPresetsRecentFirst(presets: WirePreset[]): WirePreset[] {
  return [...presets].sort((a, b) => {
    const ta = Date.parse(a.created_at);
    const tb = Date.parse(b.created_at);
    if (Number.isNaN(ta) || Number.isNaN(tb)) return 0;
    return tb - ta;
  });
}

/**
 * Card for a hardcoded starter template. Renders the template's
 * preview text inside a 9:16 chip with the actual template style
 * applied (font family, weight, color, stroke, shadow) so the
 * operator sees what they'll get before clicking. The card is purely
 * click-to-insert — no selection state, no apply button — because the
 * action is unambiguous (add a new overlay at the playhead).
 */
function StarterTemplateCard({
  template,
  onApply,
}: {
  template: StarterTemplate;
  onApply: () => void;
}) {
  const { style } = template;
  const shadowCss = style.effects.shadow
    ? `${style.effects.shadow.offsetX}px ${style.effects.shadow.offsetY}px ${style.effects.shadow.blurPx}px ${style.effects.shadow.color}`
    : undefined;
  const strokeCss = style.effects.stroke
    ? `${style.effects.stroke.widthPx}px ${style.effects.stroke.color}`
    : undefined;
  return (
    <div className="group flex flex-col gap-1.5 text-left">
      <button
        type="button"
        onClick={onApply}
        style={{ aspectRatio: "9 / 16" }}
        className="relative w-full overflow-hidden rounded-card border border-grayscale-200 bg-white transition-colors hover:border-heimdex-navy-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-heimdex-navy-500"
        aria-label={`${template.name} 템플릿 추가`}
      >
        <CheckerPattern />
        {/* Preview text sits at the same 27% top ratio the editor uses
            for starter overlays (see UNIFIED_TOP_RATIO in
            starter-templates.ts) so the card preview matches where the
            caption will actually land after the operator clicks. */}
        <div
          className="absolute inset-x-0 flex justify-center px-2"
          style={{ top: "27%", transform: "translateY(-50%)" }}
        >
          <span
            className="whitespace-pre-line text-center leading-tight"
            style={{
              fontFamily: resolveFontFamily(style.fontFamily),
              // The preview chip scales the template font down so a
              // 38px caption fits inside a ~120px wide card without
              // truncating; the renderer-side size on the canvas is
              // unchanged.
              fontSize: `${Math.max(11, Math.round(style.fontSizePx * 0.4))}px`,
              fontWeight: style.fontWeight,
              color: style.fontColor,
              textShadow: shadowCss,
              WebkitTextStroke: strokeCss,
              // Match OverlayRenderer so the card preview shows the
              // same stroke-behind look the canvas will render after
              // the operator clicks the template.
              paintOrder: strokeCss ? "stroke fill" : undefined,
              wordBreak: "keep-all",
            }}
          >
            {template.previewLabel}
          </span>
        </div>
        {/* Figma 2015:246819 — starter cards show an unfilled check
            badge in the top-right so they share the selection chrome
            with saved presets. Clicking the card applies immediately
            (single-click flow) so we don't have a "selected starter"
            state — the badge stays in its default look. */}
        <span
          aria-hidden
          className="absolute right-2 top-2 inline-flex h-5.5 w-5.5 items-center justify-center rounded-checkbox border border-grayscale-300 bg-white group-hover:border-heimdex-navy-400"
        />
      </button>
      <span className="truncate text-sm font-medium text-grayscale-800">
        {template.name}
      </span>
    </div>
  );
}

function ActionRow({
  selected,
  selectedName,
  disabled,
  onApply,
  onDelete,
  presets,
  onPickPreset,
  starterTemplates = [],
  onPickStarter,
}: {
  selected: WirePreset | null;
  selectedName: string | null;
  disabled: boolean;
  onApply: () => void;
  onDelete?: () => void;
  presets: WirePreset[];
  onPickPreset: (id: string) => void;
  starterTemplates?: readonly StarterTemplate[];
  onPickStarter?: (template: StarterTemplate) => void;
}) {
  const [open, setOpen] = useState(false);

  // Clicking 템플릿 선택 opens a list of saved presets (recent-first)
  // followed by the built-in Livenow 1/2/3 starters. Picking a saved
  // preset selects it for the 적용하기 button; picking a starter
  // applies it immediately (the starter card grid below behaves the
  // same way — single-click apply).
  const sortedPresets = sortPresetsRecentFirst(presets);

  return (
    <div className="relative flex items-center gap-2.5">
      <div className="relative flex-1">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex h-10 w-full items-center justify-between gap-2.5 rounded-card border border-grayscale-300 bg-white px-3 py-2.5 text-sm font-medium text-grayscale-800 transition-colors hover:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
          aria-expanded={open}
          aria-haspopup="listbox"
        >
          <span className={cn("truncate", !selectedName && "text-grayscale-400")}>
            {selectedName ?? "템플릿 선택"}
          </span>
          <Chevron open={open} />
        </button>
        {open && (
          <ul
            role="listbox"
            className="absolute left-0 right-0 top-full z-30 mt-1 max-h-60 overflow-y-auto rounded-card border border-grayscale-200 bg-white py-1 shadow-dialog"
          >
            {sortedPresets.length === 0 && starterTemplates.length === 0 && (
              <li className="px-3 py-2 text-xs text-grayscale-400">
                저장된 템플릿 없음
              </li>
            )}
            {sortedPresets.map((p) => (
              <li key={p.id} role="option" aria-selected={p.name === selectedName}>
                <button
                  type="button"
                  onClick={() => {
                    onPickPreset(p.id);
                    setOpen(false);
                  }}
                  className={cn(
                    "block w-full truncate px-3 py-2 text-left text-sm font-medium transition-colors hover:bg-grayscale-50",
                    p.name === selectedName
                      ? "text-heimdex-navy-600"
                      : "text-grayscale-800",
                  )}
                >
                  {p.name}
                </button>
              </li>
            ))}
            {/* Built-in starter list (Livenow 1/2/3 by default — see
                starter-templates.ts). Picking one applies it
                immediately, matching the starter card grid below. */}
            {starterTemplates.length > 0 && sortedPresets.length > 0 && (
              <li
                aria-hidden
                className="my-1 border-t border-grayscale-100"
              />
            )}
            {starterTemplates.map((t) => (
              <li key={t.id} role="option" aria-selected={false}>
                <button
                  type="button"
                  onClick={() => {
                    onPickStarter?.(t);
                    setOpen(false);
                  }}
                  className="block w-full truncate px-3 py-2 text-left text-sm font-medium text-grayscale-800 transition-colors hover:bg-grayscale-50"
                >
                  {t.name}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <button
        type="button"
        onClick={onApply}
        disabled={disabled}
        className="inline-flex h-10 items-center justify-center rounded-card bg-heimdex-navy-500 px-5 text-sm font-semibold text-white transition-colors hover:bg-heimdex-navy-600 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-heimdex-navy-500"
      >
        적용하기
      </button>

      {/* figma 2107:410711 / 2015:246806 — 선택된 템플릿을 ActionRow
          에서 바로 삭제. 카드-hover trash 와 같은 onDelete 를 공유한다.
          선택이 없으면 disabled 로 회색 처리. Ctrl+Z 미지원 (operator
          confirmed). */}
      {onDelete && (
        <button
          type="button"
          onClick={() => {
            if (selected) onDelete();
          }}
          disabled={!selected}
          aria-label={
            selected ? `${selected.name} 템플릿 삭제` : "템플릿 삭제"
          }
          data-testid="template-action-delete"
          className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-card border border-red-h-500 text-red-h-500 transition-colors hover:bg-red-h-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-h-500 disabled:cursor-not-allowed disabled:border-grayscale-200 disabled:text-grayscale-300 disabled:hover:bg-transparent"
        >
          <Trash2 className="h-5 w-5" strokeWidth={2} />
        </button>
      )}
    </div>
  );
}

function TemplateCard({
  preset,
  selected,
  onSelect,
  onDelete,
}: {
  preset: WirePreset;
  selected: boolean;
  onSelect: () => void;
  onDelete?: () => void;
}) {
  return (
    <div
      className="group flex flex-col gap-1.5 text-left"
      aria-pressed={selected}
    >
      {/* figma: 1602:41198 — 9:16 카드 (격자 패턴 + 중앙 placeholder). */}
      <button
        type="button"
        onClick={onSelect}
        style={{ aspectRatio: "9 / 16" }}
        className={cn(
          "relative w-full overflow-hidden rounded-card border bg-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-heimdex-navy-500",
          selected
            ? "border-heimdex-navy-500"
            : "border-grayscale-200 group-hover:border-heimdex-navy-400",
        )}
      >
        <CheckerPattern />

        {/* 가운데 placeholder — figma 의 "확실한 두께 자신감!"
            Composition presets carry the whole canvas (subtitle style,
            overlay set, letterbox, video transform), so the card shows
            a "전체 구성" label instead of the per-overlay placeholder
            to distinguish them from text/background presets in the
            same grid. */}
        <div className="absolute inset-0 flex items-center justify-center px-2">
          <span className="text-center text-sm font-semibold leading-snug text-heimdex-navy-500">
            {preset.kind === "composition" ? "전체 구성" : "확실한 두께 자신감!"}
          </span>
        </div>

        {/* UR4: 단일 선택 — 라디오 의미의 rounded-square 체크 인디케이터.
            토큰: w/h-5.5 (22px), rounded-checkbox (4px). */}
        <span
          aria-hidden
          className={cn(
            "absolute right-2 top-2 inline-flex h-5.5 w-5.5 items-center justify-center rounded-checkbox border transition-colors",
            selected
              ? "border-heimdex-navy-500 bg-heimdex-navy-500"
              : "border-grayscale-300 bg-white group-hover:border-heimdex-navy-400",
          )}
        >
          {selected && (
            <Check className="h-3.5 w-3.5 text-white" strokeWidth={2.5} />
          )}
        </span>
      </button>

      {/* 라벨 행 — 좌측 이름 truncate, 우측 hover-only 삭제 버튼.
          삭제는 figma 미정의 — 라벨 행 우측 휴지통 hover-show 로 head 결정. */}
      <div className="flex items-center gap-1">
        <span className="flex-1 truncate text-sm font-medium text-grayscale-800">
          {preset.name}
        </span>
        {onDelete && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            aria-label={`${preset.name} 템플릿 삭제`}
            className="hidden h-6 w-6 shrink-0 items-center justify-center rounded text-grayscale-400 transition-colors hover:bg-grayscale-100 hover:text-red-h-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-h-500 group-hover:inline-flex"
          >
            <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
        )}
      </div>
    </div>
  );
}

function CheckerPattern() {
  // 격자(체커) 패턴 — figma 1602:41198 카드 배경. svg 패턴(id 충돌 방지용
  // useId) 으로 표현.
  //
  // 2026-05-20 — operator wanted the grid to read as a "transparent
  // background" hint rather than a foreground element competing with
  // the preview text, so we dim it via opacity-30. text-grayscale-100
  // is already light; the extra alpha lets the caption read cleanly
  // while the checker pattern is still discernible.
  const id = useId();
  const patternId = `checker-${id}`;
  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full text-grayscale-100 opacity-30"
      aria-hidden
      preserveAspectRatio="none"
    >
      <defs>
        <pattern
          id={patternId}
          width="20"
          height="20"
          patternUnits="userSpaceOnUse"
        >
          <rect x="0" y="0" width="10" height="10" fill="currentColor" />
          <rect x="10" y="10" width="10" height="10" fill="currentColor" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${patternId})`} />
    </svg>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={cn(
        "h-5 w-5 shrink-0 text-grayscale-500 transition-transform",
        open && "rotate-180",
      )}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="m6 9 6 6 6-6" />
    </svg>
  );
}
