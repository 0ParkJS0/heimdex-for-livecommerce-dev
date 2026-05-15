import type { ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { WarningIcon } from "@/components/icons/figma";

type Tone = "warning" | "loading" | "info";
type Position = "bottom-center" | "top-right";

interface Props {
  tone?: Tone;
  title: ReactNode;
  body?: ReactNode;
  position?: Position;
  onClose?: () => void;
  className?: string;
}

const positionClasses: Record<Position, string> = {
  "bottom-center":
    "fixed bottom-[40px] left-1/2 -translate-x-1/2 w-[364px]",
  "top-right": "fixed top-[80px] right-[20px] w-[364px]",
};

function LeadingIcon({ tone }: { tone: Tone }) {
  if (tone === "warning") {
    return <WarningIcon className="h-[24px] w-[24px] shrink-0" />;
  }
  if (tone === "loading") {
    return (
      <span
        className="relative inline-flex h-[24px] w-[24px] shrink-0 animate-spin"
        aria-hidden="true"
      >
        <span className="absolute inset-0 rounded-full border-2 border-neutral-h-100" />
        <span className="absolute inset-0 rounded-full border-2 border-transparent border-t-heimdex-navy-500" />
      </span>
    );
  }
  return null;
}

export function Snackbar({
  tone = "warning",
  title,
  body,
  position = "bottom-center",
  onClose,
  className,
}: Props) {
  return (
    <div
      role="status"
      className={cn(
        "z-50 flex items-start gap-[8px] rounded-card bg-white p-[16px] shadow-dialog",
        positionClasses[position],
        className,
      )}
    >
      <LeadingIcon tone={tone} />
      <div className="flex min-w-0 flex-1 flex-col gap-[8px] leading-[1.4]">
        <p className="font-pretendard text-[18px] font-bold tracking-[-0.45px] text-neutral-h-800">
          {title}
        </p>
        {body ? (
          <p className="font-pretendard text-[16px] font-medium tracking-[-0.4px] text-neutral-h-600">
            {body}
          </p>
        ) : null}
      </div>
      {onClose ? (
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 text-neutral-h-500 hover:text-neutral-h-800"
          aria-label="닫기"
        >
          <X className="h-[24px] w-[24px]" strokeWidth={2} />
        </button>
      ) : null}
    </div>
  );
}
