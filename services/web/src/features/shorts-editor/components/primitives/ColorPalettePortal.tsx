"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface Props {
  anchorRef: React.RefObject<HTMLElement>;
  onClose: () => void;
  children: React.ReactNode;
}

const POPOVER_WIDTH = 260;
const POPOVER_MAX_HEIGHT = 592;
const GAP = 8;
const VIEWPORT_MARGIN = 8;

interface Pos {
  top: number;
  left: number;
}

/**
 * Portal wrapper for the color palette popover.
 *
 * Color triggers live inside the editor right wrapper, which scrolls via
 * ``overflow-y-auto``. An absolutely positioned popover inside that
 * scroll surface was getting clipped by the wrapper bounds — the palette
 * would "open" in the DOM but never become visible to the user. Portalling
 * to ``document.body`` escapes the clip, and we anchor with fixed
 * coordinates derived from the trigger's bounding rect.
 *
 * Position policy:
 *   1. Anchor the popover's right edge to the trigger's right edge
 *      (matches the figma redesign — palette opens leftward).
 *   2. Anchor the popover's top edge ``GAP`` below the trigger.
 *   3. Flip above the trigger when there isn't enough space below.
 *   4. Clamp to viewport margins so the chip can never be drawn off-
 *      screen on either axis.
 *
 * Click-outside / scroll / resize handling lives here too so the popover
 * tracks the trigger when the underlying surface scrolls.
 */
export function ColorPalettePortal({ anchorRef, onClose, children }: Props) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(false);
  const [pos, setPos] = useState<Pos>({ top: -9999, left: -9999 });

  // Defer first render to client — createPortal requires document.body.
  useEffect(() => {
    setMounted(true);
  }, []);

  const recompute = () => {
    const anchor = anchorRef.current;
    if (!anchor) return;
    const rect = anchor.getBoundingClientRect();
    const viewportH = window.innerHeight;
    const viewportW = window.innerWidth;

    // Preferred: drop below the trigger, right-aligned.
    let top = rect.bottom + GAP;
    let left = rect.right - POPOVER_WIDTH;

    // Flip above when there isn't enough room beneath the trigger but
    // there is above (popover is tall — 592px — so this matters often).
    const spaceBelow = viewportH - rect.bottom - GAP;
    const spaceAbove = rect.top - GAP;
    if (spaceBelow < POPOVER_MAX_HEIGHT && spaceAbove > spaceBelow) {
      top = rect.top - POPOVER_MAX_HEIGHT - GAP;
    }

    // Clamp inside viewport so we never paint a chip past either edge.
    if (left < VIEWPORT_MARGIN) left = VIEWPORT_MARGIN;
    if (left + POPOVER_WIDTH > viewportW - VIEWPORT_MARGIN) {
      left = viewportW - POPOVER_WIDTH - VIEWPORT_MARGIN;
    }
    if (top < VIEWPORT_MARGIN) top = VIEWPORT_MARGIN;
    if (top + POPOVER_MAX_HEIGHT > viewportH - VIEWPORT_MARGIN) {
      top = Math.max(VIEWPORT_MARGIN, viewportH - POPOVER_MAX_HEIGHT - VIEWPORT_MARGIN);
    }

    setPos({ top, left });
  };

  useLayoutEffect(() => {
    recompute();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the popover anchored when the underlying surface scrolls or the
  // window resizes. ``capture: true`` catches scroll events on nested
  // overflow containers (the editor right wrapper scrolls internally).
  useEffect(() => {
    const onChange = () => recompute();
    window.addEventListener("resize", onChange);
    window.addEventListener("scroll", onChange, true);
    return () => {
      window.removeEventListener("resize", onChange);
      window.removeEventListener("scroll", onChange, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Close when the user clicks anywhere outside the popover OR the
  // anchor. Hooking ``mousedown`` instead of ``click`` makes the close
  // happen as soon as the press lands, mirroring the native menu UX.
  useEffect(() => {
    function handle(e: MouseEvent) {
      const target = e.target as Node;
      if (popoverRef.current && popoverRef.current.contains(target)) return;
      if (anchorRef.current && anchorRef.current.contains(target)) return;
      onClose();
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [anchorRef, onClose]);

  if (!mounted) return null;

  return createPortal(
    <div
      ref={popoverRef}
      style={{ position: "fixed", top: pos.top, left: pos.left, zIndex: 50 }}
    >
      {children}
    </div>,
    document.body,
  );
}
