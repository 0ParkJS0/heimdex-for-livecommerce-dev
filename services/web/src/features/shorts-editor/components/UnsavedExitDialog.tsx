"use client";

// figma 2105:410610 (variant="new") / 2107:410657 (variant="existing")
//
// 에디터를 떠나려 할 때 (GNB 뒤로가기 / 새로고침 / 탭 닫기) 미저장 변경사항이
// 있으면 띄우는 3-action confirm. variant 는 호출부의 ``shortId`` 유무로
// 결정한다:
//
//   * "new"      — 신규 작업물 (저장 이력 없음). 카피는 "저장하지 않고
//                  나가시겠어요?" + 보조문 "저장하지 않으면 작업한
//                  내용이 모두 삭제되며, 다시 편집할 수 없습니다."
//   * "existing" — 저장본을 다시 편집 중. 카피는 "변경사항을
//                  저장하시겠어요?" + 보조문 "저장하지 않으면 마지막
//                  저장 이후 변경한 내용이 사라집니다."
//
// 두 variant 모두 동일한 3-action 행: [취소] [저장 안 함] [저장하고 나가기].

import { useEffect } from "react";
import { createPortal } from "react-dom";

import { InfoIcon } from "@/components/icons/figma";

export type UnsavedExitVariant = "new" | "existing";

interface UnsavedExitDialogProps {
  open: boolean;
  variant: UnsavedExitVariant;
  onCancel: () => void;
  onDiscard: () => void;
  onSaveAndExit: () => void;
}

const COPY: Record<
  UnsavedExitVariant,
  { title: string; body: string[] }
> = {
  new: {
    title: "저장하지 않고 나가시겠어요?",
    body: [
      "저장하지 않으면 작업한 내용이 모두 삭제되며,",
      "다시 편집할 수 없습니다.",
    ],
  },
  existing: {
    title: "변경사항을 저장하시겠어요?",
    body: ["저장하지 않으면 마지막 저장 이후 변경한", "내용이 사라집니다."],
  },
};

export function UnsavedExitDialog({
  open,
  variant,
  onCancel,
  onDiscard,
  onSaveAndExit,
}: UnsavedExitDialogProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onCancel]);

  if (!open) return null;
  if (typeof document === "undefined") return null;

  const copy = COPY[variant];

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="unsaved-exit-dialog-title"
      data-testid="unsaved-exit-dialog"
      data-variant={variant}
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex flex-col items-center justify-center gap-[20px] rounded-[20px] bg-white p-[24px] shadow-[2px_2px_20px_0px_rgba(0,0,0,0.25)]"
      >
        {/* figma 955:121744 — navy-500 disc + white "i". Shared InfoIcon component. */}
        <InfoIcon className="h-6 w-6 shrink-0" />

        <div className="flex flex-col items-center gap-[8px]">
          <p
            id="unsaved-exit-dialog-title"
            className="font-pretendard text-[18px] font-bold leading-[1.4] tracking-[-0.45px] text-neutral-h-800"
          >
            {copy.title}
          </p>
          {/* Lines are already split in COPY. whitespace-nowrap stops a single
              line from breaking at a word boundary into 3 lines (matches figma
              2105:410616). */}
          <div className="flex flex-col items-center text-center font-pretendard text-[14px] font-medium leading-[1.4] tracking-[-0.35px] text-grayscale-800">
            {copy.body.map((line, idx) => (
              <p key={idx} className="whitespace-nowrap leading-[1.4]">
                {line}
              </p>
            ))}
          </div>
        </div>

        <div className="flex items-start gap-[8px]">
          <button
            type="button"
            onClick={onCancel}
            data-testid="unsaved-exit-cancel"
            className="inline-flex h-9 items-center justify-center rounded-[8px] border border-neutral-h-500 px-[12px] py-[8px] font-pretendard text-[14px] font-semibold leading-none text-neutral-h-500 transition-colors hover:bg-neutral-h-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={onDiscard}
            data-testid="unsaved-exit-discard"
            className="inline-flex h-9 items-center justify-center rounded-[8px] border border-red-h-500 px-[12px] py-[8px] font-pretendard text-[14px] font-semibold leading-none text-red-h-500 transition-colors hover:bg-red-h-50"
          >
            저장 안 함
          </button>
          <button
            type="button"
            onClick={onSaveAndExit}
            data-testid="unsaved-exit-save"
            className="inline-flex h-9 items-center justify-center rounded-[8px] bg-heimdex-navy-500 px-[12px] py-[8px] font-pretendard text-[14px] font-semibold leading-none text-white transition-colors hover:bg-heimdex-navy-600"
          >
            저장하고 나가기
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
