"use client";

import { cn } from "@/lib/utils";
import type { GroupBy } from "../hooks/useSearch";

interface GroupByToggleProps {
  value: GroupBy;
  onChange: (value: GroupBy) => void;
}

const OPTIONS: { value: GroupBy; label: string }[] = [
  { value: "video", label: "Videos" },
  { value: "scene", label: "Scenes" },
];

export function GroupByToggle({ value, onChange }: GroupByToggleProps) {
  return (
    <div className="space-y-3">
      <label className="text-sm font-medium text-gray-700">Results</label>
      <div className="flex gap-2">
        {OPTIONS.map((option) => (
          <button
            key={option.value}
            onClick={() => onChange(option.value)}
            className={cn(
              "flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-all",
              value === option.value
                ? "bg-primary-600 text-white shadow-sm"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
