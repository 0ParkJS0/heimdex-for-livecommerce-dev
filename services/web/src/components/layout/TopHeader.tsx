"use client";

import { useAuth } from "@/lib/auth";

export function TopHeader() {
  const { user } = useAuth();
  const displayName = user?.name || user?.email || "User";

  return (
    <header className="flex h-[60px] items-center justify-end px-6">
      <div className="flex items-center gap-4">
        <button
          type="button"
          className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700"
          aria-label="알림"
        >
          <svg
            className="h-5 w-5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0"
            />
          </svg>
        </button>

        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-gray-700">
            {displayName}
          </span>
          <div className="h-9 w-9 flex-shrink-0 rounded-full bg-gray-300" />
        </div>
      </div>
    </header>
  );
}
