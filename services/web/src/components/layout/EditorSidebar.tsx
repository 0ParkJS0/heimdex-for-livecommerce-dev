"use client";

// Editor-route LNB. Uses the same nav as the global Sidebar (LnbExpanded /
// LnbRail) but expands as an overlay on top of the main content — AppLayout main
// is fixed at ml-16 for the editor so the 9:16 canvas doesn't reflow on every
// expand. Defaults to the 64px rail; PanelLeft toggles the 270px overlay.
// Route branching is handled by AppLayout's EDITOR_ROUTE_PATTERNS.

import { useState } from "react";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { LnbExpanded, LnbRail } from "./Sidebar";
import { useAttemptNavigate } from "./TopHeaderActionsContext";

export function EditorSidebar() {
  const pathname = usePathname();
  const attemptNavigate = useAttemptNavigate();
  const [expanded, setExpanded] = useState(false);

  return (
    <aside
      className={cn(
        // overlay emphasis: z-50 + transition-[width]. Expand covers main, never pushes it.
        "fixed left-0 top-0 z-50 h-screen border-r border-neutral-h-100 bg-white transition-[width] duration-200 ease-in-out",
        expanded ? "w-[270px]" : "w-16",
      )}
    >
      {expanded ? (
        <LnbExpanded
          pathname={pathname}
          onToggle={() => setExpanded(false)}
          attemptNavigate={attemptNavigate}
        />
      ) : (
        <LnbRail
          pathname={pathname}
          onToggle={() => setExpanded(true)}
          attemptNavigate={attemptNavigate}
        />
      )}
    </aside>
  );
}
