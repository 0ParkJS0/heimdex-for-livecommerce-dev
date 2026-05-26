/**
 * Render-job download driver with surfaced failure feedback.
 *
 * Pure module — no DOM, no fetch, no react. Lifts the
 * ``SavedShortsPage.handleDownload`` logic out of the page component so
 * the failure path is unit-testable without mounting the page.
 *
 * Replaces the older silent-catch pattern (``try { await download… }
 * catch {} ``) that left the operator with no feedback when a signed
 * URL had expired or the job was removed. The caller still owns the
 * failure surface (Snackbar / toast / modal) — this helper just
 * normalises the error into a Korean-default message and dispatches it
 * via the supplied ``onFailure`` sink.
 *
 * Wire shape mirrors the ``DisplayItem`` rows the SavedShorts grid
 * emits (mix of saved + render rows); the helper accepts any subset of
 * that shape so test fixtures don't have to know the full grid row.
 */

type TokenGetter = () => Promise<string | null>;

export interface DownloadableItem {
  type: "saved" | "render";
  id: string;
  status?: string;
  title?: string | null;
}

export type RenderDownloadFn = (
  jobId: string,
  filename: string,
  getToken: TokenGetter,
) => Promise<string>;

export type DownloadFailureSink = (message: string) => void;

export type DownloadOutcome = "skipped" | "downloaded" | "failed";

const FALLBACK_FAILURE_MESSAGE = "다운로드에 실패했습니다.";

/**
 * Build the .mp4 filename the browser ``a.download`` attribute uses.
 * Exposed so the helper test can pin the fallback shape (``short_<id>``)
 * without re-asserting it indirectly through the download call.
 */
export function buildDownloadFilename(item: DownloadableItem): string {
  return item.title && item.title.length > 0 ? item.title : `short_${item.id}`;
}

/**
 * Drive a single render-job download.
 *
 *   * non-render or non-completed rows return ``"skipped"`` without
 *     touching ``downloadFn`` (the JSX layer already gates the menu
 *     item on ``isCompletedRender``; this is a defence-in-depth check
 *     so the helper is safe regardless of caller).
 *   * a resolved download returns ``"downloaded"``; ``onFailure`` is
 *     never called on the success path.
 *   * a rejected download returns ``"failed"`` and invokes
 *     ``onFailure`` exactly once with the error message (or a Korean
 *     fallback when the thrown value isn't an Error).
 */
export async function runDownloadWithSnack(
  item: DownloadableItem,
  getToken: TokenGetter,
  downloadFn: RenderDownloadFn,
  onFailure: DownloadFailureSink,
): Promise<DownloadOutcome> {
  if (item.type !== "render" || item.status !== "completed") {
    return "skipped";
  }
  try {
    await downloadFn(item.id, buildDownloadFilename(item), getToken);
    return "downloaded";
  } catch (err) {
    const message =
      err instanceof Error && err.message ? err.message : FALLBACK_FAILURE_MESSAGE;
    onFailure(message);
    return "failed";
  }
}
