// Editor projects API client (L10 / T10).
//
// Thin wrapper over the /api/editor-projects endpoints. Intentionally
// NOT wired into the React layer yet — autosave hookup is a follow-up
// PR. The contract here is what the front-end will call into:
//
//   * fetchEditorProject(videoId)   → returns the saved state or null
//   * saveEditorProject(...)        → upsert; calls PUT
//   * deleteEditorProject(videoId)  → wipes the saved snapshot
//
// Autosave plumbing recommendation (for the follow-up PR):
//   1.5s idle debounce around state changes calls saveEditorProject.
//   beforeunload / visibilitychange(hidden) forces a flush so a tab
//   close doesn't strand the last keystroke.
//   Ctrl+S triggers an immediate flush.

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export interface EditorProjectResponse {
  id: string;
  video_id: string;
  title: string;
  state_json: Record<string, unknown>;
  schema_version: number;
  created_at: string;
  updated_at: string;
}

export interface EditorProjectUpsertBody {
  video_id: string;
  title?: string;
  state_json: Record<string, unknown>;
  schema_version?: number;
}

async function authHeaders(getToken: () => Promise<string | null>): Promise<HeadersInit> {
  const token = await getToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

/**
 * Fetch the saved editor project for the given video. Returns null when
 * the operator hasn't saved anything yet (server responds 404 — we
 * normalize to null because absence is a valid state on the client).
 */
export async function fetchEditorProject(
  videoId: string,
  getToken: () => Promise<string | null>,
): Promise<EditorProjectResponse | null> {
  const url = `${API_BASE}/api/editor-projects?video_id=${encodeURIComponent(videoId)}`;
  const res = await fetch(url, { headers: await authHeaders(getToken) });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to fetch editor project: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

/**
 * Upsert the editor project. Idempotent — the backend collapses by
 * (org, user, video_id) and replaces state_json + title. Safe to call
 * on every autosave tick.
 */
export async function saveEditorProject(
  body: EditorProjectUpsertBody,
  getToken: () => Promise<string | null>,
): Promise<EditorProjectResponse> {
  const url = `${API_BASE}/api/editor-projects`;
  const res = await fetch(url, {
    method: "PUT",
    headers: await authHeaders(getToken),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Failed to save editor project: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

/**
 * Remove the saved snapshot. The next editor session for the same
 * video starts from a fresh state. Used by the "discard saved
 * changes" menu item (future UI).
 */
export async function deleteEditorProject(
  videoId: string,
  getToken: () => Promise<string | null>,
): Promise<void> {
  const url = `${API_BASE}/api/editor-projects?video_id=${encodeURIComponent(videoId)}`;
  const res = await fetch(url, {
    method: "DELETE",
    headers: await authHeaders(getToken),
  });
  if (!res.ok && res.status !== 404) {
    throw new Error(`Failed to delete editor project: ${res.status} ${res.statusText}`);
  }
}
