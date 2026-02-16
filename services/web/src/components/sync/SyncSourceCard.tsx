"use client";

import { cn } from "@/lib/utils";

interface SyncSourceCardProps {
  title: string;
  onUpdate: () => void;
  isUploading?: boolean;
}

export function SyncSourceCard({
  title,
  onUpdate,
  isUploading = false,
}: SyncSourceCardProps) {
  return (
    <div className="flex flex-col justify-between rounded-xl bg-white p-6 shadow-sm">
      <div>
        <h3 className="mb-6 text-lg font-bold text-gray-900">{title}</h3>

        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">최신 분석 시간</span>
            <span className="text-sm font-semibold text-gray-900">
              2시간 전
            </span>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">연결 상태</span>
            <span className="rounded-full bg-red-50 px-3 py-0.5 text-xs font-medium text-red-500">
              연결 필요
            </span>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">상태</span>
            <span className="rounded-full bg-red-50 px-3 py-0.5 text-xs font-medium text-red-500">
              오류 있음
            </span>
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={onUpdate}
        disabled={isUploading}
        className={cn(
          "mt-8 w-full rounded-lg py-3 text-sm font-medium text-white transition-colors",
          isUploading
            ? "cursor-not-allowed bg-gray-300"
            : "bg-indigo-500 hover:bg-indigo-600"
        )}
      >
        {title} 업데이트
      </button>
    </div>
  );
}
