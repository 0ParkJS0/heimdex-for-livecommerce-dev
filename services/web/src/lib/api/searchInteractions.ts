import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

export type SearchInteractionEventType = "impression" | "click";

export interface SearchInteractionItem {
  event_type: SearchInteractionEventType;
  scene_id?: string;
  video_id?: string;
  result_position?: number;
  content_type?: "video" | "image";
}

export interface SearchInteractionPayload {
  search_event_id: number | null;
  results: SearchInteractionItem[];
}

/**
 * Fire-and-forget POST of search-result interactions (impression / click).
 *
 * Never throws and never blocks the UI — interaction analytics must not affect
 * the search experience. Always resolves to void; all failures are swallowed.
 * ``keepalive`` lets a click beacon survive the navigation it triggers.
 */
export async function postSearchInteractions(
  payload: SearchInteractionPayload,
  getToken?: TokenGetter,
): Promise<void> {
  if (payload.results.length === 0) return;
  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (getToken) {
      const token = await getToken().catch(() => null);
      if (token) headers["Authorization"] = `Bearer ${token}`;
    }
    await fetch(`${getApiBaseUrl()}/api/search/interactions`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      keepalive: true,
    });
  } catch {
    // Swallow — interaction logging must never surface to the user.
  }
}
