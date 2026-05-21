import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

/**
 * Mirror of services/api/app/modules/drive/schemas.py::SourceFact.
 * Keep field names verbatim with the backend (vitest won't catch shape drift).
 */
export interface SourceFact {
  video_id: string;
  google_file_id: string;
  file_name: string;
  file_size_bytes: number | null;
  md5_checksum: string | null;
  mount_relative_path: string;
}

export interface SourceFactsResponse {
  items: SourceFact[];
  missing: string[];
}

/** Thrown when the backend has `agent_hq_export_enabled` off (404). */
export class HqExportNotEnabledError extends Error {
  readonly notEnabled = true;
  constructor() {
    super("High-quality export is not enabled for this workspace.");
    this.name = "HqExportNotEnabledError";
  }
}

async function authHeaders(getToken: TokenGetter): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch {
    /* noop */
  }
  return headers;
}

/**
 * Fetch the per-video Drive facts the agent needs to locate ORIGINALS on the
 * local mount. Backend is org-scoped + gated behind `agent_hq_export_enabled`
 * (404 → HqExportNotEnabledError).
 */
export async function getDriveSourceFacts(
  videoIds: string[],
  getToken: TokenGetter,
): Promise<SourceFactsResponse> {
  const headers = await authHeaders(getToken);
  const qs = videoIds
    .map((v) => `video_ids=${encodeURIComponent(v)}`)
    .join("&");
  const res = await fetch(`${getApiBaseUrl()}/api/drive/source-facts?${qs}`, {
    method: "GET",
    headers,
  });
  if (res.status === 404) {
    throw new HqExportNotEnabledError();
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Failed to load source facts (${res.status})`);
  }
  return res.json();
}
