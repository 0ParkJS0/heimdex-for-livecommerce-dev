/**
 * runDownloadWithSnack — table-driven regression test for the
 * SavedShortsPage download failure surface.
 *
 * Locks the contract that replaced the older silent-catch pattern
 * (``try { await downloadRenderJob() } catch {}``) reviewed during
 * PR #265: failed downloads MUST call ``onFailure`` so the page can
 * surface a Snackbar, and successful downloads MUST NOT.
 */

import { describe, it, expect, vi } from "vitest";

import {
  buildDownloadFilename,
  runDownloadWithSnack,
  type DownloadableItem,
  type DownloadOutcome,
  type RenderDownloadFn,
} from "../lib/render-download";

const NULL_TOKEN = async () => null;

function completedItem(overrides: Partial<DownloadableItem> = {}): DownloadableItem {
  return {
    type: "render",
    id: "job_abc",
    status: "completed",
    title: "내 쇼츠",
    ...overrides,
  };
}

describe("runDownloadWithSnack", () => {
  it("skips a saved-type row and never calls the download fn", async () => {
    const downloadFn: RenderDownloadFn = vi.fn();
    const onFailure = vi.fn();
    const outcome: DownloadOutcome = await runDownloadWithSnack(
      { type: "saved", id: "saved_1" },
      NULL_TOKEN,
      downloadFn,
      onFailure,
    );
    expect(outcome).toBe("skipped");
    expect(downloadFn).not.toHaveBeenCalled();
    expect(onFailure).not.toHaveBeenCalled();
  });

  it("skips a render row that isn't completed (queued / rendering / failed / missing)", async () => {
    const downloadFn: RenderDownloadFn = vi.fn();
    const onFailure = vi.fn();
    for (const status of ["queued", "rendering", "failed", undefined]) {
      const outcome = await runDownloadWithSnack(
        { type: "render", id: "j", status },
        NULL_TOKEN,
        downloadFn,
        onFailure,
      );
      expect(outcome).toBe("skipped");
    }
    expect(downloadFn).not.toHaveBeenCalled();
    expect(onFailure).not.toHaveBeenCalled();
  });

  it("on success: resolves to 'downloaded' and does NOT touch onFailure", async () => {
    const downloadFn: RenderDownloadFn = vi.fn().mockResolvedValue("내 쇼츠.mp4");
    const onFailure = vi.fn();
    const outcome = await runDownloadWithSnack(
      completedItem(),
      NULL_TOKEN,
      downloadFn,
      onFailure,
    );
    expect(outcome).toBe("downloaded");
    expect(downloadFn).toHaveBeenCalledTimes(1);
    expect(downloadFn).toHaveBeenCalledWith("job_abc", "내 쇼츠", NULL_TOKEN);
    expect(onFailure).not.toHaveBeenCalled();
  });

  it("on failure (Error): resolves to 'failed' and surfaces error.message via onFailure exactly once", async () => {
    const downloadFn: RenderDownloadFn = vi
      .fn()
      .mockRejectedValue(new Error("Failed to download render (410)"));
    const onFailure = vi.fn();
    const outcome = await runDownloadWithSnack(
      completedItem(),
      NULL_TOKEN,
      downloadFn,
      onFailure,
    );
    expect(outcome).toBe("failed");
    expect(onFailure).toHaveBeenCalledTimes(1);
    expect(onFailure).toHaveBeenCalledWith("Failed to download render (410)");
  });

  it("on failure (non-Error throw): falls back to the Korean default message", async () => {
    const downloadFn: RenderDownloadFn = vi.fn().mockRejectedValue("network down");
    const onFailure = vi.fn();
    const outcome = await runDownloadWithSnack(
      completedItem(),
      NULL_TOKEN,
      downloadFn,
      onFailure,
    );
    expect(outcome).toBe("failed");
    expect(onFailure).toHaveBeenCalledWith("다운로드에 실패했습니다.");
  });

  it("on failure (Error with empty message): falls back to the Korean default message", async () => {
    const downloadFn: RenderDownloadFn = vi.fn().mockRejectedValue(new Error(""));
    const onFailure = vi.fn();
    await runDownloadWithSnack(completedItem(), NULL_TOKEN, downloadFn, onFailure);
    expect(onFailure).toHaveBeenCalledWith("다운로드에 실패했습니다.");
  });
});

describe("buildDownloadFilename", () => {
  it("uses the operator title when present", () => {
    expect(buildDownloadFilename({ type: "render", id: "j1", title: "내 쇼츠" })).toBe(
      "내 쇼츠",
    );
  });

  it("falls back to short_<id> when title is null", () => {
    expect(buildDownloadFilename({ type: "render", id: "j1", title: null })).toBe(
      "short_j1",
    );
  });

  it("falls back to short_<id> when title is empty string", () => {
    expect(buildDownloadFilename({ type: "render", id: "j1", title: "" })).toBe(
      "short_j1",
    );
  });

  it("falls back to short_<id> when title is undefined", () => {
    expect(buildDownloadFilename({ type: "render", id: "j1" })).toBe("short_j1");
  });
});
