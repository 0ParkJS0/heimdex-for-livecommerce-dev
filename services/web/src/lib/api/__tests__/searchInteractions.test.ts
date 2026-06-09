/**
 * Tests for postSearchInteractions — the fire-and-forget API client for
 * POST /api/search/interactions (impression / click logging). Mocks global
 * fetch; asserts URL, method, auth header, body shaping, and that failures
 * never throw.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { postSearchInteractions } from "../searchInteractions";

const getToken = () => Promise.resolve("test-token");

describe("postSearchInteractions", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs the interactions to the endpoint with auth + body", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, status: 202 });
    vi.stubGlobal("fetch", fetchMock);

    await postSearchInteractions(
      {
        search_event_id: 42,
        results: [
          { event_type: "click", scene_id: "s1", video_id: "v", result_position: 0, content_type: "video" },
        ],
      },
      getToken,
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/search/interactions");
    expect(init.method).toBe("POST");
    expect(init.headers["Authorization"]).toBe("Bearer test-token");
    const body = JSON.parse(init.body);
    expect(body.search_event_id).toBe(42);
    expect(body.results[0]).toMatchObject({
      event_type: "click",
      scene_id: "s1",
      content_type: "video",
    });
  });

  it("does not call fetch when results is empty", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await postSearchInteractions({ search_event_id: 1, results: [] }, getToken);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("swallows network errors (never throws)", async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new Error("network down"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      postSearchInteractions(
        { search_event_id: null, results: [{ event_type: "impression", scene_id: "s1" }] },
        getToken,
      ),
    ).resolves.toBeUndefined();
  });
});
