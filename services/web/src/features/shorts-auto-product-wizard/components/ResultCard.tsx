"use client";

import type { JobStatusResponse } from "@/lib/types/shorts-auto-product-wizard";
import { cn } from "@/lib/utils";

import {
  ResultStatusChip,
  deriveResultChipState,
} from "./ResultStatusChip";
import { ResultCardMenu } from "./ResultCardMenu";

interface Props {
  child: JobStatusResponse;
  /** 1-based ordinal shown as "쇼츠 N". Falls back to ``shorts_index + 1``. */
  ordinal: number;
  /** Original criteria.length_seconds for the parent scan order. */
  lengthSeconds?: number | null;
  /** Up to 2 product names to display as overlay chips. */
  productLabels?: string[];
  // figma: 1699:252725 (쇼츠 카드) — 우측 컬럼 요약 텍스트. 50자(공백 포함) 초과 시 ellipsis truncate.
  summary?: string | null;
  /**
   * Custom title set by the user via the "제목 변경" menu entry. When
   * present, replaces the default "쇼츠 {ordinal}" headline so the
   * operator's chosen label (e.g., "센트롬_강조_1") sticks.
   */
  title?: string | null;
  onRename: () => void;
  onSave?: () => void;
  onExport?: () => void;
  onCancel: () => void;
  onOpenEditor: () => void;
}

const SUMMARY_MAX_CHARS = 50;

function formatLength(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m === 0) return `${s}초`;
  if (s === 0) return `${m}분`;
  return `${m}분 ${s}초`;
}

function truncateSummary(text: string | null | undefined): string {
  if (!text) return "";
  if (text.length <= SUMMARY_MAX_CHARS) return text;
  return `${text.slice(0, SUMMARY_MAX_CHARS)}…`;
}

export function ResultCard({
  child,
  ordinal,
  lengthSeconds,
  productLabels = [],
  summary,
  title,
  onRename,
  onSave,
  onExport,
  onCancel,
  onOpenEditor,
}: Props) {
  const displayTitle = title && title.trim().length > 0 ? title : `쇼츠 ${ordinal}`;
  const state = deriveResultChipState(child);
  const isCompleted = state === "done";
  const progressPct = Math.max(0, Math.min(100, Math.round(child.progress_pct)));
  const summaryText = truncateSummary(summary);

  // The standalone "open editor" icon button (lucide/square-arrow-out-up-
  // right) was removed per the 2026-05-18 goal capture; the affordance now
  // lives on the thumbnail itself. Clicking the thumbnail invokes
  // onOpenEditor when the render is completed, matching the user-facing
  // mental model ("open this clip" = "click the clip").
  return (
    <article
      className="flex h-[253px] w-[287px] gap-[10px] rounded-card bg-white p-[10px] shadow-card"
      data-testid={`result-card-${ordinal}`}
    >
      <button
        type="button"
        onClick={onOpenEditor}
        disabled={!isCompleted}
        aria-label={isCompleted ? "편집 페이지 열기" : "쇼츠 생성 중"}
        data-testid="result-card-open-editor"
        className="group relative h-full aspect-[9/16] shrink-0 overflow-hidden rounded-[8px] bg-grayscale-800 text-left transition-opacity disabled:cursor-not-allowed"
      >
        {productLabels.length > 0 ? (
          <div className="absolute left-[8px] bottom-[8px] z-10 flex flex-wrap gap-[4px]">
            {productLabels.slice(0, 2).map((label, i) => (
              <span
                key={`${label}-${i}`}
                className="rounded-[4px] bg-black/60 px-[6px] py-[2px] font-pretendard text-[10px] font-medium text-white"
              >
                {label}
              </span>
            ))}
          </div>
        ) : null}
        {isCompleted ? (
          <span
            aria-hidden
            className="absolute inset-0 z-0 bg-transparent transition-colors group-hover:bg-black/10"
          />
        ) : null}
      </button>

      <div className="flex h-full flex-1 flex-col justify-between py-[4px]">
        <p
          className={cn(
            "font-pretendard text-[14px] font-semibold tracking-[-0.35px] leading-[1.4] line-clamp-2",
            isCompleted ? "text-grayscale-800" : "text-grayscale-800",
          )}
          data-testid="result-card-title"
          title={displayTitle}
        >
          {displayTitle}
        </p>

        <dl className="flex flex-col gap-[8px]">
          <div className="flex items-baseline justify-between">
            <dt className="font-pretendard text-[12px] font-medium text-grayscale-500">
              쇼츠 길이
            </dt>
            <dd className="font-pretendard text-[12px] font-medium text-grayscale-800">
              {formatLength(lengthSeconds)}
            </dd>
          </div>
          <div className="flex items-baseline justify-between">
            <dt className="font-pretendard text-[12px] font-medium text-grayscale-500">
              진행률
            </dt>
            <dd
              className="font-pretendard text-[12px] font-medium text-grayscale-800"
              data-testid="result-card-progress"
            >
              {progressPct}%
            </dd>
          </div>
        </dl>

        {summaryText ? (
          <p
            className="font-pretendard text-[12px] font-medium leading-[1.4] text-grayscale-600"
            data-testid="result-card-summary"
          >
            {summaryText}
          </p>
        ) : null}

        <div className="flex items-center justify-between">
          <ResultStatusChip state={state} />
        </div>
      </div>

      <div className="flex h-full w-[24px] shrink-0 flex-col items-center gap-[8px] py-[4px]">
        <ResultCardMenu
          isCompleted={isCompleted}
          onRename={onRename}
          onSave={onSave}
          onExport={onExport}
          onCancel={onCancel}
        />
      </div>
    </article>
  );
}
