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
// 2026-05-19 — responsive break (fluid ratio variant).
//
// At >= 1440 the figma sizes are pinned verbatim (474 / 352 / 371 with a
// 63px gap), so the canonical operator viewport stays pixel-identical
// to the design.
//
// Below 1440 the panels switch to a flex-ratio layout instead of a
// shrunk fixed-width set. ``flex: <grow> 1 0`` with grow values mirroring
// the figma widths (474 : 352 : 371) lets the three cards share whatever
// horizontal space the parent gives them while keeping their visual
// weight proportional to the design. The inter-card gap stays at 80px
// (matching the prior breakpoint) so the cards don't crowd the screen
// edges when the chrome (sidebar + main padding) eats into the
// viewport on common laptop sizes (1280-1366). ``shrink-0`` is removed
// from the row so it no longer forces an intrinsic min-content width
// past the viewport.
export function EditorLayout({ leftPanel, preview, rightPanel, timeline }: EditorLayoutProps) {
  return (
    <div className="flex h-full flex-col gap-[20px] overflow-hidden bg-grayscale-10">
      <div className="flex h-[626px] items-stretch gap-[80px] min-[1440px]:gap-[63px]">
        <div className="flex h-full min-w-0 flex-col overflow-hidden rounded-dialog bg-white shadow-card flex-[474_1_0%] min-[1440px]:w-[474px] min-[1440px]:flex-none">
          {leftPanel}
        </div>
        <div className="flex h-full min-w-0 items-center justify-center overflow-hidden rounded-[10px] bg-black shadow-card flex-[352_1_0%] min-[1440px]:w-[352px] min-[1440px]:flex-none">
          {preview}
        </div>
        <div className="flex h-full min-w-0 flex-col overflow-hidden rounded-dialog bg-white shadow-card flex-[371_1_0%] min-[1440px]:w-[371px] min-[1440px]:flex-none">
          {rightPanel}
        </div>
      </div>
      <div className="h-[260px] overflow-hidden rounded-dialog bg-white shadow-card">
        {timeline}
      </div>
    </div>
  );
}
