"use client";

import { cn } from "@/lib/utils";

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  /** Visible page-number window size. Default 7 (current ±3). */
  windowSize?: number;
  className?: string;
  /** Optional aria-label on the nav element. */
  ariaLabel?: string;
}

/**
 * Numbered pagination with ellipsis-style windowing.
 *
 * Shows first + last page always, with up to ``windowSize`` pages
 * around the current page. Renders an ellipsis on either side when
 * the window doesn't touch the edges, matching the pattern:
 *
 *     1 … 4 5 [6] 7 8 … 12
 *
 * Prev/next buttons guard the edges (disabled on page 1 / totalPages).
 * ``aria-current="page"`` marks the active page; the whole control
 * lives inside a ``<nav>`` with ``aria-label`` so screen readers can
 * jump past it.
 *
 * Contract:
 *   - ``onPageChange`` is called with the clicked page; callers own
 *     state. Component is otherwise stateless.
 *   - Returns ``null`` when ``totalPages <= 1`` — callers never need
 *     to conditionally render.
 */
export function Pagination({
  currentPage,
  totalPages,
  onPageChange,
  windowSize = 7,
  className,
  ariaLabel = "페이지",
}: PaginationProps) {
  if (totalPages <= 1) return null;

  const safePage = Math.min(Math.max(1, currentPage), totalPages);
  const pages = buildPageList(safePage, totalPages, windowSize);

  const btnBase =
    "inline-flex h-8 min-w-[2rem] items-center justify-center rounded px-2 text-sm transition-colors";

  return (
    <nav
      aria-label={ariaLabel}
      className={cn("flex items-center justify-center gap-1", className)}
    >
      <button
        type="button"
        disabled={safePage === 1}
        onClick={() => onPageChange(1)}
        aria-label="첫 페이지"
        className={cn(
          btnBase,
          safePage === 1
            ? "cursor-not-allowed text-gray-300"
            : "text-gray-500 hover:bg-gray-100",
        )}
      >
        &laquo;
      </button>
      <button
        type="button"
        disabled={safePage === 1}
        onClick={() => onPageChange(safePage - 1)}
        aria-label="이전 페이지"
        className={cn(
          btnBase,
          safePage === 1
            ? "cursor-not-allowed text-gray-300"
            : "text-gray-500 hover:bg-gray-100",
        )}
      >
        &lsaquo;
      </button>

      {pages.map((p, i) =>
        p === "…" ? (
          <span
            key={`gap-${i}`}
            aria-hidden="true"
            className="px-1 text-gray-400"
          >
            …
          </span>
        ) : (
          <button
            key={p}
            type="button"
            onClick={() => onPageChange(p)}
            aria-current={p === safePage ? "page" : undefined}
            aria-label={`${p} 페이지`}
            className={cn(
              btnBase,
              p === safePage
                ? "bg-indigo-500 font-medium text-white"
                : "text-gray-600 hover:bg-gray-100",
            )}
          >
            {p}
          </button>
        ),
      )}

      <button
        type="button"
        disabled={safePage === totalPages}
        onClick={() => onPageChange(safePage + 1)}
        aria-label="다음 페이지"
        className={cn(
          btnBase,
          safePage === totalPages
            ? "cursor-not-allowed text-gray-300"
            : "text-gray-500 hover:bg-gray-100",
        )}
      >
        &rsaquo;
      </button>
      <button
        type="button"
        disabled={safePage === totalPages}
        onClick={() => onPageChange(totalPages)}
        aria-label="마지막 페이지"
        className={cn(
          btnBase,
          safePage === totalPages
            ? "cursor-not-allowed text-gray-300"
            : "text-gray-500 hover:bg-gray-100",
        )}
      >
        &raquo;
      </button>
    </nav>
  );
}

/**
 * Build the displayed page list with ellipsis where appropriate.
 *
 * Rules (given the default ``windowSize=7`` and 1-indexed pages):
 *   - If ``totalPages <= windowSize``, return every page number.
 *   - Else, anchor the window on ``currentPage`` with roughly equal
 *     halves. Always include page 1 and ``totalPages``. Insert a
 *     ``"…"`` sentinel when the window starts after 2 or ends before
 *     ``totalPages - 1``.
 *
 * Exported for unit tests.
 */
export function buildPageList(
  currentPage: number,
  totalPages: number,
  windowSize: number,
): (number | "…")[] {
  if (totalPages <= windowSize) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }

  // Window always includes first + last; windowSize counts numbered
  // slots. Allocate up to 5 interior slots around currentPage so the
  // default totals 7 (1 + gap + 3 interior + gap + last).
  const half = Math.max(1, Math.floor((windowSize - 2) / 2));
  let start = Math.max(2, currentPage - half);
  let end = Math.min(totalPages - 1, currentPage + half);

  // Expand in whichever direction has headroom so the visible count
  // stays close to windowSize even near the edges.
  while (end - start + 1 < windowSize - 2 && (start > 2 || end < totalPages - 1)) {
    if (start > 2) start -= 1;
    else if (end < totalPages - 1) end += 1;
    else break;
  }

  const pages: (number | "…")[] = [1];
  if (start > 2) pages.push("…");
  for (let p = start; p <= end; p++) pages.push(p);
  if (end < totalPages - 1) pages.push("…");
  pages.push(totalPages);
  return pages;
}
