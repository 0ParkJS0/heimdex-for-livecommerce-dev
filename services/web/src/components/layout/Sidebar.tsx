"use client";

// Global LNB. figma 1607:67462 (expanded 270px) / 1670:185900 (collapsed 64px rail).
// One nav definition (메인 / 라이브러리) is rendered in both the expanded and the
// rail mode; the editor route's EditorSidebar reuses the same pieces
// (LnbExpanded / LnbRail). Every LNB link passes through ``attemptNavigate`` so a
// dirty editor can intercept the navigation (via the registered nav guard) and
// raise the UnsavedExitDialog instead of leaving silently.

import { Fragment, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bolt,
  Image as ImageIcon,
  PanelLeft,
  Save,
  Scissors,
  UserRound,
  Video,
} from "lucide-react";
import { HeimdexBrand } from "@/components/icons/figma";
import { cn } from "@/lib/utils";
import { useAttemptNavigate } from "./TopHeaderActionsContext";

// 20px nav icon, 1.6667 stroke — matches figma (same weight as the old inline SVGs).
const NAV_ICON_CLS = "h-5 w-5 shrink-0";
const NAV_ICON_STROKE = 1.6667;

export type LnbItem = { label: string; href: string; icon: ReactNode };
export type LnbSection = { title: string; items: LnbItem[] };

export const lnbSections: LnbSection[] = [
  {
    title: "메인",
    items: [
      {
        label: "동영상 검색",
        href: "/",
        icon: <Video className={NAV_ICON_CLS} strokeWidth={NAV_ICON_STROKE} aria-hidden />,
      },
      {
        label: "이미지 검색",
        href: "/images",
        icon: <ImageIcon className={NAV_ICON_CLS} strokeWidth={NAV_ICON_STROKE} aria-hidden />,
      },
    ],
  },
  {
    title: "라이브러리",
    items: [
      {
        label: "인물 라벨 관리",
        href: "/settings/people",
        icon: <UserRound className={NAV_ICON_CLS} strokeWidth={NAV_ICON_STROKE} aria-hidden />,
      },
      {
        // "교차 편집" is the renamed "가편집" — the route stays /export/preedit.
        label: "교차 편집",
        href: "/export/preedit",
        icon: <Scissors className={NAV_ICON_CLS} strokeWidth={NAV_ICON_STROKE} aria-hidden />,
      },
      {
        label: "내 쇼츠",
        href: "/export/shorts",
        icon: <Save className={NAV_ICON_CLS} strokeWidth={NAV_ICON_STROKE} aria-hidden />,
      },
    ],
  },
];

// Menus removed from the LNB (pages/routes are kept). Preserved here for a future
// restore/move:
//   - 파일 동기화 (/sync)            → moved to settings
//   - 문서 (/export/documents)
//   - 에이전트 (/agent)              → moved to settings
//   - the "Pro" badge on "이미지 검색" → removed

function isLinkActive(href: string, pathname: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

// Wraps next/link so a click first passes through the nav guard. When the guard
// intercepts (dirty editor), default navigation is blocked so the editor can
// raise its dialog.
function GuardedLink({
  href,
  attemptNavigate,
  className,
  children,
  ...rest
}: {
  href: string;
  attemptNavigate: (href: string) => boolean;
  className?: string;
  children: ReactNode;
  "aria-label"?: string;
  title?: string;
}) {
  return (
    <Link
      href={href}
      className={className}
      onClick={(e) => {
        if (!attemptNavigate(href)) e.preventDefault();
      }}
      {...rest}
    >
      {children}
    </Link>
  );
}

// figma 1607:67462 — expanded (270px) body. logo+toggle / 메인·라이브러리 / settings footer.
export function LnbExpanded({
  pathname,
  onToggle,
  attemptNavigate,
}: {
  pathname: string;
  onToggle: () => void;
  attemptNavigate: (href: string) => boolean;
}) {
  return (
    <div className="flex h-full w-[270px] flex-col justify-between p-[24px]">
      <div className="flex flex-col gap-[68px]">
        <div className="flex items-center justify-between">
          <GuardedLink
            href="/"
            attemptNavigate={attemptNavigate}
            className="flex shrink-0 items-center"
            aria-label="홈으로 이동"
          >
            <HeimdexBrand className="h-[33px] w-auto" />
          </GuardedLink>
          <button
            type="button"
            onClick={onToggle}
            className="rounded-md p-1 text-grayscale-800 transition-colors hover:bg-neutral-h-50"
            aria-label="사이드바 접기"
          >
            <PanelLeft className="h-6 w-6" strokeWidth={2} />
          </button>
        </div>

        <nav className="flex flex-col gap-[32px]">
          {lnbSections.map((section) => (
            <div key={section.title} className="flex flex-col gap-[6px]">
              <span className="text-[16px] font-semibold leading-[1.4] tracking-[-0.4px] text-neutral-h-400">
                {section.title}
              </span>
              <div className="flex flex-col items-start">
                {section.items.map((item) => {
                  const active = isLinkActive(item.href, pathname);
                  return (
                    <GuardedLink
                      key={item.href}
                      href={item.href}
                      attemptNavigate={attemptNavigate}
                      className={cn(
                        "flex items-center gap-[10px] self-start rounded-[8px] py-[10px] pl-[10px] pr-[12px] text-grayscale-800 transition-colors",
                        active ? "bg-neutral-h-100" : "hover:bg-neutral-h-50",
                      )}
                    >
                      {item.icon}
                      <span className="whitespace-nowrap text-[16px] font-semibold leading-[1.4] tracking-[-0.4px]">
                        {item.label}
                      </span>
                    </GuardedLink>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </div>

      <GuardedLink
        href="/settings"
        attemptNavigate={attemptNavigate}
        className={cn(
          "flex items-center gap-[4px] rounded-[8px] px-[4px] py-[6px] text-grayscale-800 transition-colors",
          pathname === "/settings" ? "bg-neutral-h-100" : "hover:bg-neutral-h-50",
        )}
        aria-label="설정"
      >
        <Bolt className={NAV_ICON_CLS} strokeWidth={NAV_ICON_STROKE} aria-hidden />
        <span className="text-[14px] font-semibold leading-[1.4] tracking-[-0.35px]">설정</span>
      </GuardedLink>
    </div>
  );
}

// figma 1670:185900 — collapsed (64px) rail. toggle / {메인 icons} · divider /
// {라이브러리 icons} / settings. The divider sits between sections (15×1px, neutral-100).
export function LnbRail({
  pathname,
  onToggle,
  attemptNavigate,
}: {
  pathname: string;
  onToggle: () => void;
  attemptNavigate: (href: string) => boolean;
}) {
  return (
    <div className="flex h-full w-16 flex-col items-center justify-between py-[24px]">
      <div className="flex flex-col items-center gap-[68px]">
        <button
          type="button"
          onClick={onToggle}
          className="rounded-md p-1 text-grayscale-800 transition-colors hover:bg-neutral-h-50"
          aria-label="사이드바 펼치기"
        >
          <PanelLeft className="h-6 w-6" strokeWidth={2} />
        </button>

        <nav className="flex flex-col items-center gap-[16px]">
          {lnbSections.map((section, sectionIdx) => (
            <Fragment key={section.title}>
              {sectionIdx > 0 && <div className="h-px w-[15px] bg-neutral-h-100" />}
              {section.items.map((item) => {
                const active = isLinkActive(item.href, pathname);
                return (
                  <GuardedLink
                    key={item.href}
                    href={item.href}
                    attemptNavigate={attemptNavigate}
                    title={item.label}
                    aria-label={item.label}
                    className={cn(
                      "flex h-10 w-10 items-center justify-center rounded-md text-grayscale-800 transition-colors",
                      active ? "bg-neutral-h-100" : "hover:bg-neutral-h-50",
                    )}
                  >
                    {item.icon}
                  </GuardedLink>
                );
              })}
            </Fragment>
          ))}
        </nav>
      </div>

      <GuardedLink
        href="/settings"
        attemptNavigate={attemptNavigate}
        title="설정"
        aria-label="설정"
        className={cn(
          "flex h-10 w-10 items-center justify-center rounded-md text-grayscale-800 transition-colors",
          pathname === "/settings" ? "bg-neutral-h-100" : "hover:bg-neutral-h-50",
        )}
      >
        <Bolt className={NAV_ICON_CLS} strokeWidth={NAV_ICON_STROKE} aria-hidden />
      </GuardedLink>
    </div>
  );
}

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

// LNB for non-editor routes. Toggles expanded 270px ↔ collapsed 64px rail while
// pushing the main content. Collapsed is no longer fully hidden (w-0) but a 64px rail.
export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();
  const attemptNavigate = useAttemptNavigate();

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 z-40 h-screen border-r border-neutral-h-100 bg-white transition-[width] duration-300 ease-in-out",
        collapsed ? "w-16" : "w-[270px]",
      )}
    >
      {collapsed ? (
        <LnbRail
          pathname={pathname}
          onToggle={onToggle}
          attemptNavigate={attemptNavigate}
        />
      ) : (
        <LnbExpanded
          pathname={pathname}
          onToggle={onToggle}
          attemptNavigate={attemptNavigate}
        />
      )}
    </aside>
  );
}
