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
// 2026-05-19 — continuous fluid responsive (1280 → 2560 viewport).
//
// The design canvas is 1440×1216 (operator-target screenshots ship at
// this size). The previous binary breakpoint at 1440 (PR #214 / #221)
// either clipped panels at <1440 widths or left the layout pinned at
// figma sizes that overflowed shorter viewports. This version replaces
// the breakpoint with a single clamp() per axis so the layout interpolates
// smoothly across 1280-2560 widths and 800-1440 heights, with the
// formulas calibrated to pass exactly through the figma values at the
// 1440×1216 reference point:
//
//   Horizontal gap:  63 / 1440 → 4.375vw, clamp 40-120px
//   Row height:      626 / 1216 → 51.48vh, clamp 420-880px
//   Timeline height: 260 / 1216 → 21.38vh, clamp 180-340px
//   Row→timeline gap: 20 / 1216 → 1.64vh,  clamp 12-32px
//
// Panel widths are flex-ratio (474 : 352 : 371) — they fill the row's
// horizontal extent regardless of viewport. The clamp lower bounds
// keep the layout usable at 1280×800 (smallest supported viewport)
// where pure-vh sizing would drop the timeline below a readable
// height. Clamp upper bounds cap large viewports so the layout doesn't
// balloon past sensible canvas proportions at 2560+ widths.
//
// FullscreenOverlay's phone frame is intentionally NOT responsive —
// it preserves the figma 387×688 ratio as a fixed phone-screen mock.
export function EditorLayout({ leftPanel, preview, rightPanel, timeline }: EditorLayoutProps) {
  return (
    <div className="flex h-full flex-col gap-[clamp(12px,1.64vh,32px)] overflow-hidden bg-grayscale-10">
      <div className="flex h-[clamp(420px,51.48vh,880px)] items-stretch gap-[clamp(40px,4.375vw,120px)]">
        <div className="flex h-full min-w-0 flex-col overflow-hidden rounded-dialog bg-white shadow-card flex-[474_1_0%]">
          {leftPanel}
        </div>
        <div className="flex h-full min-w-0 items-center justify-center overflow-hidden rounded-[10px] bg-black shadow-card flex-[352_1_0%]">
          {preview}
        </div>
        <div className="flex h-full min-w-0 flex-col overflow-hidden rounded-dialog bg-white shadow-card flex-[371_1_0%]">
          {rightPanel}
        </div>
      </div>
      <div className="h-[clamp(180px,21.38vh,340px)] overflow-hidden rounded-dialog bg-white shadow-card">
        {timeline}
      </div>
    </div>
  );
}
