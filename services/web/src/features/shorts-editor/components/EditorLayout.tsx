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
  // 2026-05-22 — outer wrapper now allows horizontal scroll instead of
  // clipping with overflow-hidden. At narrow viewports (< 1440) the
  // row content's natural width (474 + 352 preview + 371 + 126 gap =
  // ~1323 + sidebar + padding ≈ 1440) exceeded the outer width, and
  // overflow-hidden was clipping the right panel while the timeline
  // (w-full) stayed at the smaller outer width — that's the alignment
  // bug the operator flagged on WSL Chrome. Letting the wrapper scroll
  // horizontally keeps row + timeline matched (both grow to the same
  // min-w) at the cost of an occasional horizontal scrollbar.
  return (
    <div className="flex h-full flex-col overflow-x-auto overflow-y-hidden bg-grayscale-10 pl-[24px] pr-[29px] pt-[20px] pb-[20px]">
      {/* Inner wrapper pinned at the figma 1440 row min width so both
          the row (with min-w children) and the timeline cell below
          share the same content box. ``min-w-fit`` was tempting here
          but resolved to the timeline's full intrinsic horizontal
          scroll content (~25k px on a long clip), which then bloated
          the row's flex-grow children. 1323 = 474 (left) + 352
          (preview at h=626 max) + 371 (right) + 126 (2× 63 gap).
          Below the threshold the outer wrapper scrolls horizontally. */}
      <div className="flex min-w-[1323px] flex-col gap-[20px]">
      {/* Row height clamp: header(80) + editor.pt(20) + row + gap(20)
          + timeline(252) + editor.pb(20) = 100vh → row = 100vh − 392px.
          (AppLayout drops its own main pb-6 in editor mode so the 20-px
          bottom gap isn't doubled.) Clamped to [420, 626] so the preview's
          9:16 box never gets impossibly small or larger than the figma
          reference. Bottom gap stays at 20 px across viewports ≥1018h
          (row=626 ceiling) and 812–1018h (clamp range); below 812h the
          floor wins and outer scroll kicks in instead. */}
      <div className="flex h-[clamp(420px,calc(100vh-392px),626px)] items-stretch gap-[63px]">
        {/* Side panels pinned at the figma reference widths (474 / 371)
            as a HARD min so the right panel never shrinks below the
            point where its 변형/위치 X label clips. The earlier max-w
            (720 / 560) was removed 2026-05-22 — on wider viewports the
            panels capped at their max while the timeline below kept
            growing to fill the outer wrapper, which left the right
            panel's right edge ~125 px inside the timeline's right edge
            and broke the visual alignment. Letting both grow with
            outer width keeps every right edge in the same column. */}
        <div className="flex h-full min-w-[474px] flex-col overflow-hidden rounded-dialog bg-white shadow-card flex-[474_1_0%]">
          {leftPanel}
        </div>
        <div className="flex aspect-[9/16] h-full shrink-0 items-center justify-center overflow-hidden rounded-[10px] bg-black shadow-card">
          {preview}
        </div>
        <div className="flex h-full min-w-[371px] flex-col overflow-hidden rounded-dialog bg-white shadow-card flex-[371_1_0%]">
          {rightPanel}
        </div>
      </div>
      {/* Timeline cell — figma 2045:329988 wrapper height (~252 px) at
          1440 ratio. Stays at this height regardless of viewport size
          or how many subtitle/overlay tracks the operator adds —
          tracks-area inside the panel scrolls vertically instead of
          pushing the wrapper down. The outer's pb-[20px] guarantees the
          bottom-of-timeline → bottom-of-screen gap is always 20px. */}
      <div className="h-[252px] shrink-0 overflow-hidden rounded-dialog bg-white shadow-card">
        {timeline}
      </div>
      </div>
    </div>
  );
}
