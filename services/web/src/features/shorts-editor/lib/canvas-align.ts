/**
 * Canvas alignment helper — compute the normalized transform.x / transform.y
 * the overlay should land on so its outer edge lines up flush against the
 * preview canvas edge.
 *
 * Overlay positioning model (see preview/OverlayRenderer.tsx:411):
 *   left: ${transform.x * 100}%
 *   top:  ${transform.y * 100}%
 *   transform: translate(-50%, -50%)
 *
 * The translate(-50%) means transform.x / transform.y address the overlay's
 * geometric center. Aligning the overlay's left edge to the canvas left
 * edge therefore means x = (overlayWidth / 2) / canvasWidth, not x = 0.
 *
 * We resolve the overlay's rendered size by querying the live DOM through
 * data-overlay-id, so the same code path works for backgrounds (explicit
 * widthPx / heightPx) and text (auto-sized — widthPx is null in state but
 * the rendered span still has a measurable bounding box).
 */

export type CanvasAlignAxis = "x" | "y";
export type CanvasAlignPosition = "start" | "center" | "end";

/**
 * Compute the new transform.x or transform.y the overlay should be assigned
 * to land on the requested edge. Returns 0.5 for center. For start / end,
 * measures the rendered overlay element and its canvas container so the
 * overlay's outer edge touches the canvas outer edge (B-mode anchor
 * correction the operator asked for on 2026-05-20). When the DOM isn't
 * mounted yet — caller invoked too early, overlay not rendered — falls
 * back to 0.01 / 0.99 so a single press still moves the overlay decisively.
 */
export function computeCanvasAlignTarget(
  overlayId: string,
  axis: CanvasAlignAxis,
  position: CanvasAlignPosition,
): number {
  if (position === "center") return 0.5;

  const fallback = position === "start" ? 0.01 : 0.99;

  if (typeof document === "undefined") return fallback;

  const overlayEl = document.querySelector<HTMLElement>(
    `[data-overlay-id="${overlayId}"]`,
  );
  if (!overlayEl) return fallback;

  // The overlay container is absolutely positioned inside the preview
  // canvas wrapper. Its offsetParent is exactly that wrapper.
  const canvasEl = overlayEl.offsetParent as HTMLElement | null;
  if (!canvasEl) return fallback;

  const overlayRect = overlayEl.getBoundingClientRect();
  const canvasRect = canvasEl.getBoundingClientRect();
  if (canvasRect.width <= 0 || canvasRect.height <= 0) return fallback;

  const halfRatio =
    axis === "x"
      ? overlayRect.width / 2 / canvasRect.width
      : overlayRect.height / 2 / canvasRect.height;

  return position === "start" ? halfRatio : 1 - halfRatio;
}
