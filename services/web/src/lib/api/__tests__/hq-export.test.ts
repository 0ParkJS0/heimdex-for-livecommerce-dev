import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getDriveSourceFacts,
  HqExportNotEnabledError,
} from "@/lib/api/hq-export";

const originalFetch = global.fetch;
const getToken = async () => "tok";

beforeEach(() => vi.resetAllMocks());
afterEach(() => {
  global.fetch = originalFetch;
});

describe("getDriveSourceFacts", () => {
  it("builds a repeated video_ids query and returns the response", async () => {
    const payload = {
      items: [
        {
          video_id: "gd_a",
          google_file_id: "g1",
          file_name: "a.mp4",
          file_size_bytes: 10,
          md5_checksum: "abc",
          mount_relative_path: "My Drive/a.mp4",
        },
      ],
      missing: [],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => payload });
    global.fetch = fetchMock as unknown as typeof fetch;

    const res = await getDriveSourceFacts(["gd_a", "gd_b"], getToken);
    expect(res).toEqual(payload);

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/api/drive/source-facts?");
    expect(url).toContain("video_ids=gd_a");
    expect(url).toContain("video_ids=gd_b");
    // Auth header forwarded
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  it("throws HqExportNotEnabledError on 404 (flag off)", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }) as unknown as typeof fetch;
    await expect(getDriveSourceFacts(["gd_a"], getToken)).rejects.toBeInstanceOf(
      HqExportNotEnabledError,
    );
  });

  it("throws a generic error on other failures", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ detail: "boom" }),
    }) as unknown as typeof fetch;
    await expect(getDriveSourceFacts(["gd_a"], getToken)).rejects.toThrow("boom");
  });
});
