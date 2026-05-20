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
// 2026-05-20 — re-anchor to 1440×1024 (LNB inside) with FIXED gutters.
//
// Previous revisions clamped almost every dimension to a viewport-scaled
// formula, which meant the operator-reference horizontal spacing
// (24 / 63 / 63 / 29) drifted at every viewport other than 1440. The
// new contract from #design (Slack 2026-05-20) keeps those gutters
// strictly fixed and only lets the side panels and timeline flex.
//
// Horizontal contract (post-LNB body width = viewport - 64px LNB):
//
//   24px   subtitle left gutter
//   474px  subtitle wrapper (flex-grow)
//   63px   gap → preview
//   352px  preview (locked via aspect-[9/16] on 626 row height)
//   63px   gap → text/bg/template
//   371px  text/bg/template wrapper (flex-grow)
//   29px   right gutter
//
// At 1440 viewport: 64 + 24 + 474 + 63 + 352 + 63 + 371 + 29 = 1440 ✓
//
// Vertical contract (1024 viewport, GNB rendered outside):
//
//   20px   top gutter (below GNB)
//   626px  row (preview drives this via 9:16)
//   20px   row → timeline gap
//   ??px   timeline (fills remaining)
//   20px   bottom gutter
//
// Responsive behavior:
//
//   • Side panels stay at flex-[474_1_0%] : flex-[371_1_0%] so the
//     horizontal slack from a wider viewport is divided in the same
//     56 : 44 ratio the figma anchor uses.
//   • Side panels carry min-w / max-w guardrails so a narrow viewport
//     doesn't crush the toolbar (min) and a 2560+ viewport doesn't
//     balloon them past usable widths (max). Defaults below.
//   • Preview keeps aspect-[9/16] + h-full, so its width follows the
//     row height. The row height clamps between 420 (short viewports)
//     and 626 (≥1024 viewport). Below 420 the row scrolls.
//   • Timeline takes the remaining vertical space with a 180 floor and
//     500 ceiling so it stays usable at every viewport.
//
// Defaults applied (2026-05-20, operator OK):
//
//   min-w  subtitle 320 / text/bg 280
//   max-w  subtitle 720 / text/bg 560 (PR #243 caps preserved)
//   timeline min 180 / max 500
//   row    min 420 / max 626
//
// FullscreenOverlay's phone frame is intentionally NOT responsive —
// it preserves the figma 387×688 ratio as a fixed phone-screen mock.
export function EditorLayout({ leftPanel, preview, rightPanel, timeline }: EditorLayoutProps) {
  return (
    <div className="flex h-full flex-col gap-[20px] overflow-hidden bg-grayscale-10 pl-[24px] pr-[29px] pt-[20px] pb-[20px]">
      <div className="flex h-[clamp(420px,calc(100vh-240px),626px)] items-stretch gap-[63px]">
        <div className="flex h-full min-w-[320px] max-w-[720px] flex-col overflow-hidden rounded-dialog bg-white shadow-card flex-[474_1_0%]">
          {leftPanel}
        </div>
        <div className="flex aspect-[9/16] h-full shrink-0 items-center justify-center overflow-hidden rounded-[10px] bg-black shadow-card">
          {preview}
        </div>
        <div className="flex h-full min-w-[280px] max-w-[560px] flex-col overflow-hidden rounded-dialog bg-white shadow-card flex-[371_1_0%]">
          {rightPanel}
        </div>
      </div>
      <div className="min-h-[180px] max-h-[500px] flex-1 overflow-hidden rounded-dialog bg-white shadow-card">
        {timeline}
      </div>
    </div>
  );
}
