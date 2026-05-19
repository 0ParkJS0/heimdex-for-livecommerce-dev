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
// 2026-05-20 — enforce 9:16 on the preview wrapper.
//
// The previous version used flex-[352_1_0%] on the preview, which let
// the center column stretch with the rest of the row. At anything
// other than the exact 1440×1216 anchor the preview ended up off the
// 9:16 ratio that the rendered MP4 expects — operators saw captions
// land at canvas coordinates that didn't survive export. The center
// column now uses ``aspect-[9/16]`` with ``h-full shrink-0`` so its
// width is derived strictly from the row height, locking the editor
// preview to the same ratio as the output frame. Side panels keep
// their flex ratios (474 : 371) and share whatever horizontal space
// is left over.
//
// Side panels are also capped with ``max-w-[clamp(...)]`` so that at
// 2560+ viewports they don't balloon to 1000+ px and dwarf their
// internal toolbar controls. The caps land near 1.5× the figma widths
// (474 → 720, 371 → 560) — enough room to breathe at wide viewports,
// not so wide that the controls feel marooned.
//
// The parent column adds a matching bottom inset
// ``pb-[clamp(12px,1.64vh,32px)]`` so the timeline keeps a visible
// gap from the viewport bottom edge across the same vertical scaling
// window the row/timeline clamps already use.
//
// FullscreenOverlay's phone frame is intentionally NOT responsive —
// it preserves the figma 387×688 ratio as a fixed phone-screen mock.
export function EditorLayout({ leftPanel, preview, rightPanel, timeline }: EditorLayoutProps) {
  return (
    <div className="flex h-full flex-col gap-[clamp(12px,1.64vh,32px)] overflow-hidden bg-grayscale-10 pb-[clamp(12px,1.64vh,32px)]">
      <div className="flex h-[clamp(420px,51.48vh,880px)] items-stretch justify-center gap-[clamp(40px,4.375vw,120px)]">
        <div className="flex h-full min-w-0 max-w-[clamp(420px,33vw,720px)] flex-col overflow-hidden rounded-dialog bg-white shadow-card flex-[474_1_0%]">
          {leftPanel}
        </div>
        <div className="flex aspect-[9/16] h-full shrink-0 items-center justify-center overflow-hidden rounded-[10px] bg-black shadow-card">
          {preview}
        </div>
        <div className="flex h-full min-w-0 max-w-[clamp(340px,26vw,560px)] flex-col overflow-hidden rounded-dialog bg-white shadow-card flex-[371_1_0%]">
          {rightPanel}
        </div>
      </div>
      <div className="mx-auto h-[clamp(180px,21.38vh,340px)] w-full max-w-[clamp(1080px,90vw,1840px)] overflow-hidden rounded-dialog bg-white shadow-card">
        {timeline}
      </div>
    </div>
  );
}
