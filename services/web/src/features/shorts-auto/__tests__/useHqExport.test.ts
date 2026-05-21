import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { useHqExport, extractVideoIds } from "../hooks/useHqExport";
import { getShortComposition } from "@/lib/api/shorts-render";
import { getDriveSourceFacts } from "@/lib/api/hq-export";
import { startAgentHqRender } from "@/lib/agent";

vi.mock("@/lib/api/shorts-render", () => ({
  getShortComposition: vi.fn(),
}));
vi.mock("@/lib/api/hq-export", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/api/hq-export")>();
  return { ...actual, getDriveSourceFacts: vi.fn() };
});
vi.mock("@/lib/agent", () => ({
  startAgentHqRender: vi.fn(),
  getAgentHqRenderStatus: vi.fn(),
  getAgentHqRenderOutputUrl: (id: string) => `http://127.0.0.1:8787/hq-render/${id}/output`,
}));

const getComp = vi.mocked(getShortComposition);
const getFacts = vi.mocked(getDriveSourceFacts);
const startRender = vi.mocked(startAgentHqRender);
const getToken = async () => "tok";

beforeEach(() => vi.resetAllMocks());

describe("extractVideoIds", () => {
  it("dedupes video_ids from scene_clips", () => {
    expect(
      extractVideoIds({ scene_clips: [{ video_id: "a" }, { video_id: "a" }, { video_id: "b" }] }),
    ).toEqual(["a", "b"]);
  });
  it("handles missing scene_clips", () => {
    expect(extractVideoIds({})).toEqual([]);
  });
});

describe("useHqExport", () => {
  it("done immediately → state done with output URL", async () => {
    getComp.mockResolvedValue({ composition: { scene_clips: [{ video_id: "gd_a" }] }, source: "render_job" });
    getFacts.mockResolvedValue({
      items: [{ video_id: "gd_a", google_file_id: "g", file_name: "a.mp4", file_size_bytes: 1, md5_checksum: null, mount_relative_path: "My Drive/a.mp4" }],
      missing: [],
    });
    startRender.mockResolvedValue({ job_id: "ag1", status: "done", width: 1218, height: 2160 });

    const { result } = renderHook(() => useHqExport(getToken));
    await act(async () => {
      await result.current.start("rj1");
    });

    const st = result.current.getState("rj1");
    expect(st.kind).toBe("done");
    if (st.kind === "done") {
      expect(st.outputUrl).toBe("http://127.0.0.1:8787/hq-render/ag1/output");
    }
    // The agent received the composition as the opaque spec.
    expect(startRender).toHaveBeenCalledWith(
      expect.objectContaining({ spec: { scene_clips: [{ video_id: "gd_a" }] } }),
    );
  });

  it("missing sources → failed", async () => {
    getComp.mockResolvedValue({ composition: { scene_clips: [{ video_id: "gd_a" }] }, source: "render_job" });
    getFacts.mockResolvedValue({ items: [], missing: ["gd_a"] });

    const { result } = renderHook(() => useHqExport(getToken));
    await act(async () => {
      await result.current.start("rj1");
    });
    const st = result.current.getState("rj1");
    expect(st.kind).toBe("failed");
    if (st.kind === "failed") expect(st.error).toContain("찾을 수 없");
    expect(startRender).not.toHaveBeenCalled();
  });

  it("source-facts disabled (404) → failed with not-enabled message", async () => {
    const { HqExportNotEnabledError } = await import("@/lib/api/hq-export");
    getComp.mockResolvedValue({ composition: { scene_clips: [{ video_id: "gd_a" }] }, source: "render_job" });
    getFacts.mockRejectedValue(new HqExportNotEnabledError());

    const { result } = renderHook(() => useHqExport(getToken));
    await act(async () => {
      await result.current.start("rj1");
    });
    const st = result.current.getState("rj1");
    expect(st.kind).toBe("failed");
    if (st.kind === "failed") expect(st.error).toContain("not enabled");
  });

  it("composition with no scene_clips → failed before any agent call", async () => {
    getComp.mockResolvedValue({ composition: { scene_clips: [] }, source: "render_job" });

    const { result } = renderHook(() => useHqExport(getToken));
    await act(async () => {
      await result.current.start("rj1");
    });
    expect(result.current.getState("rj1").kind).toBe("failed");
    expect(getFacts).not.toHaveBeenCalled();
  });
});
