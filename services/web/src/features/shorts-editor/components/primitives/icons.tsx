/**
 * SVG icons for the V2 panel toolbars.
 *
 * Hand-rolled to avoid pulling in a full icon library for ~10 icons.
 * All have stroke-based geometry so they inherit `currentColor`.
 */

const ICON_PROPS = {
  className: "h-4 w-4",
  fill: "none",
  viewBox: "0 0 24 24",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function PlusIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M12 5v14m-7-7h14" />
    </svg>
  );
}

export function TrashIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14z" />
    </svg>
  );
}

export function BoldIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M7 4h6a4 4 0 010 8H7zM7 12h7a4 4 0 010 8H7z" />
    </svg>
  );
}

export function ItalicIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M19 4h-9M14 20H5M15 4L9 20" />
    </svg>
  );
}

export function UnderlineIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M6 4v8a6 6 0 0012 0V4M5 20h14" />
    </svg>
  );
}

export function AlignLeftIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M3 6h18M3 12h12M3 18h18" />
    </svg>
  );
}

export function AlignCenterIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M3 6h18M6 12h12M3 18h18" />
    </svg>
  );
}

export function AlignRightIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M3 6h18M9 12h12M3 18h18" />
    </svg>
  );
}

export function LineSpacingIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M5 4l-2 2m2-2l2 2m-2-2v16m0 0l-2-2m2 2l2-2M11 6h10M11 12h10M11 18h10" />
    </svg>
  );
}

export function LayerStackIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M12 2L2 7l10 5 10-5-10-5z" />
      <path d="M2 17l10 5 10-5M2 12l10 5 10-5" />
    </svg>
  );
}

export function PaintBucketIcon({ className }: { className?: string }) {
  // figma 1602:40067 — lucide/paint-bucket. The earlier path was actually
  // lucide/eraser (the diagonal-stroke shape staging users saw). Swapped
  // for the canonical paint-bucket: tilted body + dripping paint drop.
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="m19 11-8-8-8.6 8.6a2 2 0 0 0 0 2.8l5.2 5.2c.8.8 2 .8 2.8 0L19 11Z" />
      <path d="m5 2 5 5" />
      <path d="M2 13h15" />
      <path d="M22 20a2 2 0 1 1-4 0c0-1.6 1.7-2.4 2-4 .3 1.6 2 2.4 2 4Z" />
    </svg>
  );
}

// Canvas-level alignment trigger — Lucide ``align-center-horizontal``
// glyph: a long center bar with two short bars hanging below and two
// short bars pinned above. Default (unrotated) state represents
// horizontal centering on the x axis (x = 0.5); ``rotated`` applies a
// 90deg clockwise transform so the same path doubles as the vertical
// center (y = 0.5) icon.
//
// 2026-05-20 — swapped the hand-rolled "two rounded rectangles + line"
// shape for the Lucide ``align-center-horizontal`` path so the editor's
// canvas-align trigger reads as the same icon the rest of the design
// system uses (Slack #team-uiux 2026-05-19). Source asset preserved
// at its native 20×20 viewBox; consumers size via className.
export function CanvasAlignCenterIcon({
  className,
  rotated = false,
}: { className?: string; rotated?: boolean }) {
  return (
    <svg
      {...ICON_PROPS}
      viewBox="0 0 20 20"
      strokeWidth={1.66667}
      className={className ?? ICON_PROPS.className}
      style={rotated ? { transform: "rotate(90deg)" } : undefined}
    >
      <path d="M1.66675 10.0003H18.3334M8.33341 13.3337V16.667C8.33341 17.109 8.15782 17.5329 7.84526 17.8455C7.5327 18.1581 7.10878 18.3337 6.66675 18.3337H5.00008C4.55805 18.3337 4.13413 18.1581 3.82157 17.8455C3.50901 17.5329 3.33341 17.109 3.33341 16.667V13.3337M8.33341 6.66699V3.33366C8.33341 2.89163 8.15782 2.46771 7.84526 2.15515C7.5327 1.84259 7.10878 1.66699 6.66675 1.66699H5.00008C4.55805 1.66699 4.13413 1.84259 3.82157 2.15515C3.50901 2.46771 3.33341 2.89163 3.33341 3.33366V6.66699M16.6667 13.3337V14.167C16.6667 14.609 16.4912 15.0329 16.1786 15.3455C15.866 15.6581 15.4421 15.8337 15.0001 15.8337H13.3334C12.8914 15.8337 12.4675 15.6581 12.1549 15.3455C11.8423 15.0329 11.6667 14.609 11.6667 14.167V13.3337M11.6667 6.66699V5.83366C11.6667 4.91699 12.4167 4.16699 13.3334 4.16699H15.0001C15.4421 4.16699 15.866 4.34259 16.1786 4.65515C16.4912 4.96771 16.6667 5.39163 16.6667 5.83366V6.66699" />
    </svg>
  );
}

export function ImageIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="M21 15l-5-5L5 21" />
    </svg>
  );
}

export function ChevronDownIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? "h-3 w-3"}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}
