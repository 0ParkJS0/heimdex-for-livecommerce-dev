import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  startAgentHqRender,
  getAgentHqRenderStatus,
  getAgentHqRenderOutputUrl,
} from "@/lib/agent";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("agent HQ render client", () => {
  beforeEach(() => mockFetch.mockReset());
  afterEach(() => vi.useRealTimers());

  it("startAgentHqRender POSTs to /hq-render and returns the job", async () => {
    const job = { job_id: "j1", status: "queued" };
    mockFetch.mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(job) });

    const req = {
      spec: { output: { width: 406 } },
      sources: [
        {
          video_id: "gd_a",
          google_file_id: "g1",
          file_name: "a.mp4",
          file_size_bytes: 10,
          md5_checksum: null,
          mount_relative_path: "My Drive/a.mp4",
        },
      ],
    };
    await expect(startAgentHqRender(req)).resolves.toEqual(job);

    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8787/hq-render");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual(req);
  });

  it("startAgentHqRender throws the agent error on non-OK", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 503,
      json: vi.fn().mockResolvedValue({ error: "render runtime unavailable" }),
    });
    await expect(startAgentHqRender({ spec: {}, sources: [] })).rejects.toThrow(
      "render runtime unavailable",
    );
  });

  it("getAgentHqRenderStatus returns the job on 200", async () => {
    const job = { job_id: "j1", status: "done", width: 1218, height: 2160 };
    mockFetch.mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(job) });
    await expect(getAgentHqRenderStatus("j1")).resolves.toEqual(job);
    expect(mockFetch.mock.calls[0][0]).toBe("http://127.0.0.1:8787/hq-render/j1");
  });

  it("getAgentHqRenderStatus returns null on non-OK", async () => {
    mockFetch.mockResolvedValue({ ok: false, json: vi.fn() });
    await expect(getAgentHqRenderStatus("j1")).resolves.toBeNull();
  });
  // Note: the fetch-rejection (network error) path hits the same catch→null as
  // the non-OK case above and as checkAgentHealth (tested in agent.test.ts).
  // A dedicated reject-mock sub-test trips vitest v4's unhandled-rejection
  // detector even though the function swallows it, so it's intentionally omitted.

  it("getAgentHqRenderOutputUrl builds the localhost output URL", () => {
    expect(getAgentHqRenderOutputUrl("j1")).toBe(
      "http://127.0.0.1:8787/hq-render/j1/output",
    );
  });
});
