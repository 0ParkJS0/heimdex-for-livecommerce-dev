"use client";

// figma: 2107:410685 — 에디터 화면 나가기 팝업(저장 후 추가 편집).
// 렌더가 완료되었을 때 자동 redirect 대신 띄우는 두-선택 모달.
//   * 계속 편집 → 다이얼로그 닫고 에디터 유지 (resetRender 호출은
//     호출부에서 결정)
//   * 내 쇼츠로 이동 → /export/shorts

import { useEffect } from "react";
import { createPortal } from "react-dom";

import { Check } from "lucide-react";

interface RenderCompleteDialogProps {
  open: boolean;
  onContinueEditing: () => void;
  onGoToShorts: () => void;
}

export function RenderCompleteDialog({
  open,
  onContinueEditing,
  onGoToShorts,
}: RenderCompleteDialogProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      // ESC = 계속 편집 (덜 destructive 한 쪽).
      if (e.key === "Escape") onContinueEditing();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onContinueEditing]);

  if (!open) return null;
  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="render-complete-dialog-title"
      data-testid="render-complete-dialog"
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/40 p-4"
      onClick={onContinueEditing}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex flex-col items-center justify-center gap-[20px] rounded-[20px] bg-white p-[24px] shadow-[2px_2px_20px_0px_rgba(0,0,0,0.25)]"
      >
        {/* figma 2107:410686 — 24px rounded check badge, fill #3FB675. */}
        <div
          className="inline-flex h-6 w-6 items-center justify-center rounded-full"
          style={{ backgroundColor: "#3FB675" }}
          aria-hidden
        >
          <Check className="h-3.5 w-3.5 text-white" strokeWidth={3} />
        </div>

        <div className="flex flex-col items-center gap-[8px]">
          <p
            id="render-complete-dialog-title"
            className="font-pretendard text-[18px] font-bold leading-[1.4] tracking-[-0.45px] text-neutral-h-800"
          >
            저장이 완료되었습니다
          </p>
          <p className="font-pretendard text-[14px] font-medium leading-[1.4] tracking-[-0.35px] text-grayscale-800">
            계속 편집하시겠어요, 아니면 내 쇼츠로 이동하시겠어요?
          </p>
        </div>

        <div className="flex items-start gap-[8px]">
          <button
            type="button"
            onClick={onContinueEditing}
            data-testid="render-complete-continue"
            className="inline-flex h-9 items-center justify-center rounded-[8px] border border-neutral-h-500 px-[12px] py-[8px] font-pretendard text-[14px] font-semibold leading-none text-neutral-h-500 transition-colors hover:bg-neutral-h-50"
          >
            계속 편집
          </button>
          <button
            type="button"
            onClick={onGoToShorts}
            data-testid="render-complete-go-to-shorts"
            className="inline-flex h-9 items-center justify-center rounded-[8px] bg-heimdex-navy-500 px-[12px] py-[8px] font-pretendard text-[14px] font-semibold leading-none text-white transition-colors hover:bg-heimdex-navy-600"
          >
            내 쇼츠로 이동
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
