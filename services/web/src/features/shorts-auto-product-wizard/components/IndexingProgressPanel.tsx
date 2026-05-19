// figma: 1713:288103  (cache: .figma-cache/1713-288103_phase2_wizard-indexing.api.json)
// node-name: Component2-6.b AI 쇼츠 생성(인덱싱 중)
// ============================================================================
// Inline-wizard step 2-1 (인덱싱 진행) progress panel.
//
// 2026-05-19 — goal-mock revision. The pill layout is restored (icon +
// label live INSIDE each pill) but the connectors and centering are
// tightened so the four stages always read on a single horizontal row,
// centered inside the parent wrapper. Key fixes vs the previous attempt:
//   - panel root spans the host wrapper (``flex-1`` + ``items-center``)
//     so the stepper centers vertically/horizontally instead of sitting
//     at the wrapper's top-left
//   - each pill is ``whitespace-nowrap`` so "분석 중" / "상품 확인" /
//     "분류 중" / "마무리 중" never break to a vertical character stack
//   - connectors are short fixed-width lines flush against the pill
//     edges (no inter-pill padding)
//   - completed marker = the Figma green check (also at
//     public/icons/check-step.svg) inlined as SVG so first paint
//     doesn't pay an extra request
// ============================================================================

"use client";

import { Button } from "@/components/ui/figma-index";
import { formatVideoTimestampHMS } from "@/lib/timeline";
import { cn } from "@/lib/utils";

import type { WizardCriteriaDraft } from "./InlineWizardCriteriaPanel";

const NAVY = "#234C77";
const QUEUED_BORDER = "#E5E7EB";
const QUEUED_TEXT = "#9CA3AF";

export type IndexingStage =
  | "enumerating"
  | "tracking"
  | "assembling"
  | "rendering";

const STAGES: ReadonlyArray<{ id: IndexingStage; label: string }> = [
  { id: "enumerating", label: "분석 중" },
  { id: "tracking", label: "상품 확인" },
  { id: "assembling", label: "분류 중" },
  { id: "rendering", label: "마무리 중" },
];

interface Props {
  criteria?: WizardCriteriaDraft;
  videoDurationMs?: number;
  /** Overall progress in [0, 1]. */
  progress: number;
  /** The currently active stage, or null if queued. */
  currentStage: IndexingStage | null;
  /** Stages already finished, in pipeline order. */
  completedStages?: ReadonlyArray<IndexingStage>;
  hideHeaderActions?: boolean;
  hidePercent?: boolean;
  /** Accepted for backward-compat, never read. */
  estimatedRemainingSeconds?: number;
  /** Drop the outer white card + heading row. */
  bare?: boolean;
}

function distributionLabel(value: WizardCriteriaDraft["product_distribution"]) {
  return value === "single" ? "상품별 쇼츠" : "통합 쇼츠";
}

function summaryChip(
  criteria: WizardCriteriaDraft,
  durationMs: number,
): string {
  const start = criteria.time_range_start_ms ?? 0;
  const end = criteria.time_range_end_ms ?? durationMs;
  return [
    distributionLabel(criteria.product_distribution),
    `${formatVideoTimestampHMS(start)} - ${formatVideoTimestampHMS(end)}`,
    `${criteria.length_seconds}초 길이`,
    `${criteria.requested_count}개 생성`,
  ].join(" · ");
}

function clampPercent(progress: number): number {
  if (Number.isNaN(progress)) return 0;
  return Math.max(0, Math.min(100, Math.round(progress * 100)));
}

function CheckIcon({ color = "white" }: { color?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M17 8.66211L10.125 15.5371L7 12.4121"
        stroke={color}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Spinner({ tone }: { tone: "active" | "queued" }) {
  const ringColor = tone === "active" ? NAVY : QUEUED_TEXT;
  return (
    <span
      className="inline-block h-[14px] w-[14px] animate-spin rounded-full"
      style={{
        border: "2px solid #E5E7EB",
        borderTopColor: ringColor,
      }}
      aria-hidden="true"
    />
  );
}

export function IndexingProgressPanel({
  criteria,
  videoDurationMs,
  progress,
  currentStage,
  completedStages = [],
  hideHeaderActions = false,
  hidePercent = false,
  bare = false,
}: Props) {
  const percent = clampPercent(progress);
  const completedSet = new Set<string>(completedStages);
  const showHeaderActions =
    !hideHeaderActions && criteria != null && videoDurationMs != null;

  const stepperRow = (
    <ol
      className="flex items-center justify-center"
      data-testid="indexing-stage-list"
      aria-label="쇼츠 생성 파이프라인"
    >
      {STAGES.map((stage, i) => {
        const isCompleted = completedSet.has(stage.id);
        const isActive = !isCompleted && currentStage === stage.id;
        const state: "completed" | "active" | "queued" = isCompleted
          ? "completed"
          : isActive
            ? "active"
            : "queued";
        return (
          <li
            key={stage.id}
            className="flex items-center"
            data-testid={`indexing-stage-${stage.id}`}
            data-state={state}
          >
            <span
              className={cn(
                "flex items-center gap-[6px] whitespace-nowrap rounded-full px-[14px] py-[8px] text-[13px] font-semibold tracking-[-0.3px] transition",
                isCompleted && "text-white",
                isActive && "border-2 bg-white",
                state === "queued" && "border bg-white",
              )}
              style={
                isCompleted
                  ? { backgroundColor: NAVY }
                  : isActive
                    ? { borderColor: NAVY, color: NAVY }
                    : { borderColor: QUEUED_BORDER, color: QUEUED_TEXT }
              }
            >
              {isCompleted ? (
                <CheckIcon color="white" />
              ) : (
                <Spinner tone={isActive ? "active" : "queued"} />
              )}
              <span>{stage.label}</span>
            </span>
            {/* Short connector line flush against the pill edges. */}
            {i < STAGES.length - 1 ? (
              <span
                aria-hidden="true"
                data-testid="indexing-stage-connector"
                className="h-[2px] w-[20px]"
                style={{
                  backgroundColor: isCompleted ? NAVY : QUEUED_BORDER,
                }}
              />
            ) : null}
          </li>
        );
      })}
    </ol>
  );

  const body = (
    <>
      {!bare ? (
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-[20px] font-semibold tracking-[-0.5px] text-grayscale-800">
            AI 쇼츠 생성
          </h2>
          {showHeaderActions ? (
            <div className="flex items-center gap-[12px]">
              <span
                className="rounded-full bg-neutral-h-50 px-[12px] py-[6px] text-[12px] font-medium text-grayscale-500"
                data-testid="indexing-summary-chip"
              >
                {summaryChip(criteria!, videoDurationMs!)}
              </span>
              <Button variant="primary" size="sm" disabled>
                다음
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Centring layer — ``flex-1`` lets this absorb whatever vertical
          space the host wrapper has (943×454) so the stepper row sits
          in the middle of that surface instead of clinging to its
          top-left. */}
      <div className="flex w-full flex-1 flex-col items-center justify-center gap-[16px]">
        {stepperRow}

        <div className="flex flex-col items-center gap-[4px]">
          {!hidePercent ? (
            <p
              className="text-[16px] font-semibold leading-[1.4] tracking-[-0.4px]"
              style={{ color: NAVY }}
              data-testid="indexing-progress-percent"
            >
              {percent}%
            </p>
          ) : null}
          <p
            className="text-[14px] font-medium tracking-[-0.35px] text-neutral-h-600"
            data-testid="indexing-progress-eta"
          >
            보통 30-90초 소요
          </p>
        </div>
      </div>
    </>
  );

  if (bare) {
    return (
      <div
        className="flex w-full flex-1 flex-col font-pretendard"
        data-testid="indexing-progress-bare"
      >
        {body}
      </div>
    );
  }

  return (
    <div className="space-y-[20px] font-pretendard">
      <div className="space-y-[40px] rounded-card bg-white p-[20px] shadow-card">
        {body}
      </div>
    </div>
  );
}
