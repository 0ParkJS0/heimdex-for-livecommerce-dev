"use client";

import type { ReactNode } from "react";

interface EditorLayoutProps {
  leftPanel: ReactNode;
  preview: ReactNode;
  rightPanel: ReactNode;
  timeline: ReactNode;
}

// figma: 1602:37722 / 1602:37844 / 1663:45752 — editor body = three cards
// in the upper row (subtitle 474×626, video 352×626, text/bg/template 371×626)
// plus the timeline at the bottom. All wrappers share the dialog radius and
// card shadow.
//
// 2026-05-19 — responsive break. The figma frame is pinned at 1440; at
// that viewport and above we render the original sizes verbatim. Below
// 1440 the fixed 474/352/371 + 63px gap clipped against the screen edge
// and surfaced a horizontal scrollbar, so the layout now drops to a
// slightly tighter set of widths AND widens the inter-wrapper gap. The
// growing gap is intentional — when the side margins shrink to zero the
// three cards crowd against the screen edges, so giving them more
// inter-card breathing room reads as "feels more spacious" even though
// the cards themselves are individually narrower.
export function EditorLayout({ leftPanel, preview, rightPanel, timeline }: EditorLayoutProps) {
  return (
    <div className="flex h-full flex-col gap-[20px] overflow-hidden bg-grayscale-10">
      <div className="flex h-[626px] shrink-0 items-stretch gap-[80px] min-[1440px]:gap-[63px]">
        <div className="flex h-full w-[400px] min-w-0 flex-col overflow-hidden rounded-dialog bg-white shadow-card min-[1440px]:w-[474px]">
          {leftPanel}
        </div>
        <div className="flex h-full w-[300px] shrink-0 items-center justify-center overflow-hidden rounded-[10px] bg-black shadow-card min-[1440px]:w-[352px]">
          {preview}
        </div>
        <div className="flex h-full w-[320px] flex-col overflow-hidden rounded-dialog bg-white shadow-card min-[1440px]:w-[371px]">
          {rightPanel}
        </div>
      </div>
      <div className="h-[260px] overflow-hidden rounded-dialog bg-white shadow-card">
        {timeline}
      </div>
    </div>
  );
}
