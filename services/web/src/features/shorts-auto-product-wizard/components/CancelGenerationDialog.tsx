"use client";

import { Dialog } from "@/components/ui/Dialog";

interface Props {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function CancelGenerationDialog({ open, onClose, onConfirm }: Props) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="취소하시겠어요?"
      body="취소한 영상은 복구할 수 없어요."
      icon="warning"
      secondary={{ label: "닫기", onClick: onClose }}
      primary={{ label: "취소", variant: "danger", onClick: onConfirm }}
    />
  );
}
