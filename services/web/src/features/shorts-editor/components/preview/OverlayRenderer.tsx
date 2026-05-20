"use client";

import { type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";

import { resolveFontFamily } from "@/lib/fonts";
import { cn } from "@/lib/utils";
import type {
  EditorBackgroundOverlay,
  EditorOverlay,
  EditorTextOverlay,
  EffectsProps,
  ShadowProps,
  TransformProps,
} from "../../lib/overlay-types";

type Corner = "nw" | "ne" | "sw" | "se";

interface OverlayRendererProps {
  overlay: EditorOverlay;
  isSelected: boolean;
  // Body drag — caller wires this to a "move" gesture that updates
  // overlay.transform.x / .y.
  onMovePointerDown?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  // Corner drag — caller wires this to a "resize" gesture that updates
  // fontSizePx (text) or transform.widthPx/heightPx (background).
  onResizePointerDown?: (
    corner: Corner,
    e: ReactPointerEvent<HTMLDivElement>,
  ) => void;
  // Corner-outer drag — caller wires this to a "rotate" gesture that
  // updates transform.rotationDeg. The handle sits slightly outside
  // each resize corner so the user gets a free-rotation affordance
  // when their cursor drifts diagonally past the resize square.
  onRotatePointerDown?: (
    corner: Corner,
    e: ReactPointerEvent<HTMLDivElement>,
  ) => void;
  // Drag continuation — these MUST be attached to the same elements that
  // call setPointerCapture in the pointerdown handlers, otherwise the
  // captured element delivers events to nowhere and the gesture appears
  // frozen. (Symptom in V2 v1: handles render but dragging does nothing.)
  onPointerMove?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onClick?: () => void;
}

/**
 * Renders an EditorOverlay (text or background) as a positioned, styled
 * <div>/<p> in the preview canvas. Pure: no state, no network — caller
 * controls selection + drag math.
 *
 * Drag UX (matches V1 PreviewPanel's subtitle behavior):
 * - Body pointerdown → caller-driven "move" — translates X/Y delta into
 *   normalized transform.x/y updates.
 * - Corner pointerdown (when selected) → caller-driven "resize" —
 *   translates radial distance ratio into a proportional fontSizePx
 *   (text) or widthPx/heightPx (background) update.
 *
 * Visual fidelity:
 * - Browser kerning vs PIL kerning will drift slightly (Risk 3 in plan).
 * - Stroke is rendered via -webkit-text-stroke (text) or outline (bg).
 * - Shadow uses CSS text-shadow stack / box-shadow (with spread).
 */
export function OverlayRenderer({
  overlay,
  isSelected,
  onMovePointerDown,
  onResizePointerDown,
  onRotatePointerDown,
  onPointerMove,
  onPointerUp,
  onClick,
}: OverlayRendererProps) {
  const sharedProps = {
    isSelected,
    onMovePointerDown,
    onResizePointerDown,
    onRotatePointerDown,
    onPointerMove,
    onPointerUp,
    onClick,
  };
  if (overlay.kind === "text") {
    return <TextOverlayBox overlay={overlay} {...sharedProps} />;
  }
  return <BackgroundOverlayBox overlay={overlay} {...sharedProps} />;
}

// ---------------------------------------------------------------------------
// Text overlay
// ---------------------------------------------------------------------------

function TextOverlayBox({
  overlay,
  isSelected,
  onMovePointerDown,
  onResizePointerDown,
  onRotatePointerDown,
  onPointerMove,
  onPointerUp,
  onClick,
}: {
  overlay: EditorTextOverlay;
  isSelected: boolean;
  onMovePointerDown?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onResizePointerDown?: (
    corner: Corner,
    e: ReactPointerEvent<HTMLDivElement>,
  ) => void;
  onRotatePointerDown?: (
    corner: Corner,
    e: ReactPointerEvent<HTMLDivElement>,
  ) => void;
  onPointerMove?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onClick?: () => void;
}) {
  const containerStyle = positionContainerStyle(overlay.transform, overlay.layerIndex);

  const textStyle: CSSProperties = {
    fontFamily: resolveFontFamily(overlay.fontFamily),
    // 2026-05-20 — container-query scale. ``fontSizePx`` is stored in
    // 720-tall output coords; ``100cqh / 720`` resolves to a fraction
    // of px on whatever preview canvas this overlay lands on (preview,
    // fullscreen modal, etc — each surface must set ``container-type:
    // size`` on its canvas wrapper). Math.max floor keeps tiny stored
    // sizes legible at 8px minimum. Replaces the prior static 0.5
    // multiplier which only matched one specific surface size.
    fontSize: `max(8px, calc(${overlay.fontSizePx} * 100cqh / 720))`,
    fontWeight: overlay.fontWeight,
    fontStyle: overlay.italic ? "italic" : "normal",
    textDecoration: overlay.underline ? "underline" : "none",
    color: overlay.fontColor,
    textAlign: overlay.textAlign,
    lineHeight: overlay.lineHeight,
    letterSpacing: `${overlay.letterSpacing * 0.05}em`,
    padding: "2px 6px",
    borderRadius: "2px",
    whiteSpace: "pre-wrap",
    ...textShadowAndStrokeStyles(overlay.effects),
    ...(overlay.highlightColor
      ? {
          backgroundColor: overlay.highlightColor,
          opacity: overlay.highlightOpacity,
        }
      : {}),
  };

  return (
    <div
      data-overlay-id={overlay.id}
      style={{
        ...containerStyle,
        opacity: overlay.effects.opacity,
        // 2026-05-19 — without `width: max-content` the absolute box's
        // auto-width is capped by the parent's right edge. When the
        // operator drags the overlay near the right side of the canvas
        // the available right-of-anchor space shrinks, forcing the
        // <p>'s pre-wrap text to wrap and the box to grow tall
        // (operator reported the caption "stretching vertically as it
        // approached the right edge"). max-content keeps the box at
        // the text's intrinsic single-line width regardless of where
        // it sits on the canvas; visually it may extend past the
        // preview frame, but the box no longer reshapes mid-drag.
        width: "max-content",
      }}
      className={cn(
        "absolute select-none cursor-grab active:cursor-grabbing",
        isSelected && "ring-2 ring-indigo-400 ring-offset-1",
      )}
      onPointerDown={onMovePointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
    >
      {overlay.text === "" ? (
        <div
          className="h-12 w-12 rounded bg-red-500/70"
          aria-label="empty text overlay placeholder"
        />
      ) : (
        <p style={textStyle}>{overlay.text}</p>
      )}

      {isSelected && onResizePointerDown && (
        <ResizeHandles
          onResize={onResizePointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        />
      )}
      {isSelected && onRotatePointerDown && (
        <RotateHandles
          onRotate={onRotatePointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Background overlay
// ---------------------------------------------------------------------------

function BackgroundOverlayBox({
  overlay,
  isSelected,
  onMovePointerDown,
  onResizePointerDown,
  onRotatePointerDown,
  onPointerMove,
  onPointerUp,
  onClick,
}: {
  overlay: EditorBackgroundOverlay;
  isSelected: boolean;
  onMovePointerDown?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onResizePointerDown?: (
    corner: Corner,
    e: ReactPointerEvent<HTMLDivElement>,
  ) => void;
  onRotatePointerDown?: (
    corner: Corner,
    e: ReactPointerEvent<HTMLDivElement>,
  ) => void;
  onPointerMove?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onClick?: () => void;
}) {
  const containerStyle = positionContainerStyle(
    overlay.transform,
    overlay.layerIndex,
  );

  // When imageUrl is set the overlay carries a user-picked picture; we
  // paint it via background-image (cover) over the underlying fillColor
  // so transparent fills produce a clean image overlay and solid fills
  // still tint underneath if the operator picked a colour.
  const boxStyle: CSSProperties = {
    // 2026-05-20 — widthPx/heightPx are stored in 405×720 output coords;
    // re-scale to the actual preview canvas via container queries so a
    // 200px-wide background stays at the same proportion on every
    // surface (inline preview, fullscreen modal, exported MP4). Same
    // pattern as the text fontSize handling in TextOverlayBox above.
    width: `calc(${overlay.transform.widthPx ?? 100} * 100cqw / 405)`,
    height: `calc(${overlay.transform.heightPx ?? 60} * 100cqh / 720)`,
    backgroundColor: overlay.fillColor,
    ...(overlay.imageUrl
      ? {
          backgroundImage: `url(${overlay.imageUrl})`,
          // "contain" keeps the picture's natural aspect ratio inside
          // the overlay box (2026-05-18 review). Use "cover" instead
          // when the box has been explicitly sized to the canvas, e.g.
          // for full-frame stills.
          backgroundSize: "contain",
          backgroundPosition: "center",
          backgroundRepeat: "no-repeat",
        }
      : {}),
    ...(overlay.effects.stroke
      ? {
          outline: `${overlay.effects.stroke.widthPx}px solid ${overlay.effects.stroke.color}`,
          outlineOffset: 0,
        }
      : {}),
    ...(overlay.effects.shadow
      ? {
          boxShadow: cssBoxShadow(overlay.effects.shadow),
        }
      : {}),
  };

  return (
    <div
      data-overlay-id={overlay.id}
      style={{ ...containerStyle, opacity: overlay.effects.opacity }}
      className={cn(
        "absolute select-none cursor-grab active:cursor-grabbing",
        isSelected && "ring-2 ring-indigo-400 ring-offset-1",
      )}
      onPointerDown={onMovePointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
    >
      <div style={boxStyle} />

      {isSelected && onResizePointerDown && (
        <ResizeHandles
          onResize={onResizePointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        />
      )}
      {isSelected && onRotatePointerDown && (
        <RotateHandles
          onRotate={onRotatePointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Resize handles (4 corners)
// ---------------------------------------------------------------------------

const CORNER_STYLES: Record<Corner, string> = {
  nw: "-top-1.5 -left-1.5 cursor-nwse-resize",
  ne: "-top-1.5 -right-1.5 cursor-nesw-resize",
  sw: "-bottom-1.5 -left-1.5 cursor-nesw-resize",
  se: "-bottom-1.5 -right-1.5 cursor-nwse-resize",
};

// Rotation handles sit one step further diagonally out from the
// resize handles so the operator gets a free-rotation affordance the
// moment their cursor drifts past the resize square. Operator-tested
// offset: ~16px past the corner, which lands the handle just outside
// the visible focus ring but still within easy thumb reach on
// touchpads.
const ROTATE_CORNER_STYLES: Record<Corner, string> = {
  nw: "-top-5 -left-5 cursor-grab active:cursor-grabbing",
  ne: "-top-5 -right-5 cursor-grab active:cursor-grabbing",
  sw: "-bottom-5 -left-5 cursor-grab active:cursor-grabbing",
  se: "-bottom-5 -right-5 cursor-grab active:cursor-grabbing",
};

function ResizeHandles({
  onResize,
  onPointerMove,
  onPointerUp,
}: {
  onResize: (corner: Corner, e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerMove?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp?: (e: ReactPointerEvent<HTMLDivElement>) => void;
}) {
  return (
    <>
      {(["nw", "ne", "sw", "se"] as const).map((corner) => (
        <div
          key={corner}
          className={cn(
            "absolute z-10 h-3 w-3 rounded-full border-2 border-white bg-indigo-500",
            CORNER_STYLES[corner],
          )}
          onPointerDown={(e) => onResize(corner, e)}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          // Stop click bubbling so corner clicks don't double as
          // body-clicks (which would re-fire selection).
          onClick={(e) => e.stopPropagation()}
        />
      ))}
    </>
  );
}

// Rotation handles — small ghosted dots positioned one notch
// diagonally outside the resize squares. Visually understated so they
// don't compete with the resize affordance, but reachable with a
// slight outward drift of the cursor. Drag math (angle delta around
// the overlay's center) lives in PreviewPanel's pointermove branch.
function RotateHandles({
  onRotate,
  onPointerMove,
  onPointerUp,
}: {
  onRotate: (corner: Corner, e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerMove?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp?: (e: ReactPointerEvent<HTMLDivElement>) => void;
}) {
  return (
    <>
      {(["nw", "ne", "sw", "se"] as const).map((corner) => (
        <div
          key={`rotate-${corner}`}
          aria-label={`Rotate ${corner}`}
          className={cn(
            "absolute z-10 h-2.5 w-2.5 rounded-full border border-white bg-indigo-300/70",
            ROTATE_CORNER_STYLES[corner],
          )}
          onPointerDown={(e) => onRotate(corner, e)}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onClick={(e) => e.stopPropagation()}
        />
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Style helpers
// ---------------------------------------------------------------------------

function positionContainerStyle(
  transform: TransformProps,
  layerIndex: number,
): CSSProperties {
  return {
    left: `${transform.x * 100}%`,
    top: `${transform.y * 100}%`,
    transform: `translate(-50%, -50%) rotate(${transform.rotationDeg}deg)`,
    pointerEvents: "auto",
    zIndex: layerIndex,
  };
}

function textShadowAndStrokeStyles(e: EffectsProps): CSSProperties {
  const out: CSSProperties = {};
  if (e.stroke) {
    // 2026-05-19 — paint-order: stroke fill so the stroke renders
    // BEHIND the glyph fill. The default paint order for SVG/text
    // (fill, stroke, markers) draws the stroke on top, so the
    // letter shape gets visually eaten by the stroke at higher
    // widths. Putting `stroke` first means the fill sits cleanly
    // on top — the outline reads as a halo behind the letter, not
    // a thickening of its own outline.
    (out as CSSProperties & {
      WebkitTextStroke?: string;
      paintOrder?: string;
    }).WebkitTextStroke = `${e.stroke.widthPx}px ${e.stroke.color}`;
    (out as CSSProperties & { paintOrder?: string }).paintOrder =
      "stroke fill";
  }
  if (e.shadow) {
    out.textShadow = cssTextShadow(e.shadow);
  }
  return out;
}

function cssTextShadow(s: ShadowProps): string {
  if (s.spreadPx > 0) {
    const offsets: Array<[number, number]> = [];
    const r = Math.max(1, s.spreadPx);
    for (let dx = -r; dx <= r; dx += Math.max(1, Math.floor(r / 2))) {
      for (let dy = -r; dy <= r; dy += Math.max(1, Math.floor(r / 2))) {
        offsets.push([s.offsetX + dx, s.offsetY + dy]);
      }
    }
    return offsets
      .map(([x, y]) => `${x}px ${y}px ${s.blurPx}px ${s.color}`)
      .join(", ");
  }
  return `${s.offsetX}px ${s.offsetY}px ${s.blurPx}px ${s.color}`;
}

function cssBoxShadow(s: ShadowProps): string {
  return `${s.offsetX}px ${s.offsetY}px ${s.blurPx}px ${s.spreadPx}px ${s.color}`;
}
