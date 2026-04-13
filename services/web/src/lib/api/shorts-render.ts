import { getApiBaseUrl } from "./utils";
import type { RenderJobResponse } from "./highlight-reel";

export type { RenderJobResponse };

type TokenGetter = () => Promise<string | null>;

export interface RenderJobListResponse {
  items: RenderJobResponse[];
  total: number;
}

/**
 * Thrown when the backend returns 429 Too Many Requests on
 * POST /api/shorts/render. The UI should surface this as a "wait a
 * moment" message distinct from a generic submission failure so the
 * user understands retrying immediately won't help.
 */
export class RenderRateLimitError extends Error {
  readonly isRateLimit = true;
  constructor(message: string) {
    super(message);
    this.name = "RenderRateLimitError";
  }
}

export interface CompositionResponse {
  composition: Record<string, unknown>;
  source: "render_job" | "generated";
}

async function authHeaders(getToken: TokenGetter): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }
  return headers;
}

export async function submitRender(
  composition: Record<string, unknown>,
  videoId: string,
  title: string | null,
  getToken: TokenGetter,
): Promise<RenderJobResponse> {
  const headers = await authHeaders(getToken);
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/render`, {
    method: "POST",
    headers,
    body: JSON.stringify({ video_id: videoId, title, composition }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    const message = detail.detail || `Render submission failed (${res.status})`;
    if (res.status === 429) {
      throw new RenderRateLimitError(message);
    }
    throw new Error(message);
  }
  return res.json();
}

export async function listRenderJobs(
  getToken: TokenGetter,
  limit = 20,
  offset = 0,
): Promise<RenderJobListResponse> {
  const headers = await authHeaders(getToken);
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/render?${params}`, {
    method: "GET",
    headers,
  });
  if (!res.ok) {
    throw new Error(`Failed to list render jobs (${res.status})`);
  }
  return res.json();
}

export async function getShortComposition(
  shortId: string,
  getToken: TokenGetter,
): Promise<CompositionResponse> {
  const headers = await authHeaders(getToken);
  const res = await fetch(`${getApiBaseUrl()}/api/shorts/${shortId}/composition`, {
    method: "GET",
    headers,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Failed to get composition (${res.status})`);
  }
  return res.json();
}
