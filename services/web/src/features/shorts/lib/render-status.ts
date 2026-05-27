/**
 * Render-status predicates shared between the SavedShortsPage card grid
 * and its dependent UI (dot-3 menu items, status pill, summary block).
 *
 * Pure module — no DOM, no fetch, no react. Stays this way so the
 * predicates can be tested without mounting the page.
 *
 * Wire shape: ``items`` mixes saved-shorts rows (``type === "saved"``)
 * with render-job rows (``type === "render"`` + a ``status`` of
 * ``queued | rendering | completed | failed``). Predicates only inspect
 * the two fields they need; anything else on the row is opaque.
 */

export interface RenderStatusItem {
  type: "saved" | "render";
  status?: string;
}

/** Render job is still working — queued OR actively rendering. */
export function isRenderingRender(item: RenderStatusItem): boolean {
  return (
    item.type === "render" &&
    (item.status === "queued" || item.status === "rendering")
  );
}

/** Render job finished cleanly and has a downloadable artifact. */
export function isCompletedRender(item: RenderStatusItem): boolean {
  return item.type === "render" && item.status === "completed";
}

/** Render job stopped with an error. No download URL. */
export function isFailedRender(item: RenderStatusItem): boolean {
  return item.type === "render" && item.status === "failed";
}
