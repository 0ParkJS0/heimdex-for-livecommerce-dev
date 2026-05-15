"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { t } from "../lib/i18n/strings";

interface Props {
  open: boolean;
  onClose: () => void;
  onSave: (name: string, isShared: boolean) => void | Promise<void>;
}

// Standalone modal: the Phase 0 `Dialog` primitive wraps its body in <p>,
// which cannot legally host form controls. Mirrors Dialog's visual tokens
// (rounded-dialog, shadow-dialog, p-[24px], Button primitive) so it reads
// as part of the same dialog family.
export function TemplateSaveDialog({ open, onClose, onSave }: Props) {
  const [name, setName] = useState("");
  const [isShared, setIsShared] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName("");
    setIsShared(false);
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  const canSubmit = name.trim().length > 0;
  const handleSubmit = () => {
    if (canSubmit) void onSave(name.trim(), isShared);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex w-[360px] flex-col gap-[20px] rounded-dialog bg-white p-[24px] shadow-dialog"
      >
        <p className="font-pretendard text-[18px] font-bold tracking-[-0.45px] leading-[1.4] text-neutral-h-800">
          {t.preset.dialogTitle}
        </p>

        <div className="flex flex-col gap-[8px]">
          <input
            type="text"
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSubmit();
            }}
            placeholder={t.preset.namePlaceholder}
            className="w-full rounded-lg border border-grayscale-200 bg-white px-3 py-2 text-sm text-grayscale-800 placeholder-grayscale-400 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
          />
          <label className="flex items-center gap-2 text-xs text-grayscale-500">
            <input
              type="checkbox"
              checked={isShared}
              onChange={(e) => setIsShared(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-grayscale-200 text-heimdex-navy-500 focus:ring-heimdex-navy-500"
            />
            {t.preset.shareToggleLabel}
          </label>
        </div>

        <div className="flex justify-end gap-[8px]">
          <Button variant="secondary" size="md" onClick={onClose}>
            {t.preset.dialogCancel}
          </Button>
          <Button
            variant="primary"
            size="md"
            onClick={handleSubmit}
            disabled={!canSubmit}
          >
            {t.preset.dialogConfirm}
          </Button>
        </div>
      </div>
    </div>
  );
}
