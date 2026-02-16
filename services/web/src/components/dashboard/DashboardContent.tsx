"use client";

import { useState, useCallback, useMemo } from "react";
import Link from "next/link";
import { useSearch } from "@/features/search/hooks/useSearch";
import { cn } from "@/lib/utils";

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
      />
    </svg>
  );
}

function VideoIcon() {
  return (
    <svg className="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z" />
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg className="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg className="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
    </svg>
  );
}

function EmptyStateIcon() {
  return (
    <svg className="h-16 w-16 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
    </svg>
  );
}

function formatDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export default function DashboardContent() {
  const [query, setQuery] = useState("");
  const { handleSearch, response, isLoading } = useSearch();

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (query.trim()) {
        handleSearch(query.trim());
      }
    },
    [query, handleSearch],
  );

  const dateRange = useMemo(() => {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 7);
    return { start: formatDate(start), end: formatDate(end) };
  }, []);

  const videoCount = response?.results?.length ?? 0;
  const hasResults = videoCount > 0;

  return (
    <div className="mx-auto max-w-5xl pt-4">
      <div className="rounded-xl bg-white p-6 shadow-sm">
        <h2 className="mb-5 text-lg font-bold text-gray-900">
          전체 아카이브 내 검색
        </h2>

        <form onSubmit={handleSubmit} className="flex items-center gap-3">
          <div className="relative flex-1">
            <SearchIcon className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="전체 아카이브에서 검색하고 싶은 영상을 찾아보세요"
              className="w-full rounded-lg border border-gray-200 bg-gray-50 py-3 pl-12 pr-4 text-sm text-gray-900 placeholder:text-gray-400 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            />
          </div>
          <button
            type="submit"
            disabled={isLoading || !query.trim()}
            className={cn(
              "rounded-lg px-6 py-3 text-sm font-medium transition-colors",
              query.trim()
                ? "bg-indigo-500 text-white hover:bg-indigo-600"
                : "bg-gray-200 text-gray-400 cursor-not-allowed",
            )}
          >
            검색
          </button>
        </form>
      </div>

      <div className="mt-4 rounded-xl bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-gray-900">검색된 영상</h2>
          <div className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600">
            <CalendarIcon />
            <span>{dateRange.start}</span>
            <span className="text-gray-300">|</span>
            <span>{dateRange.end}</span>
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between border-b border-gray-100 pb-4">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-1.5 text-sm text-gray-600">
              <VideoIcon />
              <span>{videoCount} videos</span>
            </div>
            <div className="flex items-center gap-1.5 text-sm text-gray-600">
              <FolderIcon />
              <span>0 folders</span>
            </div>
            <div className="flex items-center gap-1.5 text-sm text-gray-600">
              <ClockIcon />
              <span>N/A</span>
            </div>
          </div>
          <button
            type="button"
            className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
          >
            생성 일자순
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
            </svg>
          </button>
        </div>

        {!hasResults && (
          <div className="flex flex-col items-center py-20">
            <EmptyStateIcon />
            <h3 className="mt-6 text-lg font-bold text-gray-900">
              검색할 영상이 없습니다.
            </h3>
            <p className="mt-2 text-sm text-gray-500">
              파일 동기화부터 진행해주세요.
            </p>
            <Link
              href="/sync"
              className="mt-6 inline-flex items-center gap-1.5 rounded-lg bg-indigo-500 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-indigo-600"
            >
              파일 동기화로 이동
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
              </svg>
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
