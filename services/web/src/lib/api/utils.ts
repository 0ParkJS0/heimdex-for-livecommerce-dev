/**
 * Resolve the API base URL dynamically.
 *
 * Priority:
 *  1. NEXT_PUBLIC_API_URL env var (if non-empty) — used in local dev
 *  2. window.location.origin (browser) — production/staging multi-subdomain
 *  3. "" (SSR fallback, currently unused — all callers are "use client")
 */
const _ENV_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
export function getApiBaseUrl(): string {
  if (_ENV_API_URL) return _ENV_API_URL;
  if (typeof window !== "undefined") return window.location.origin;
  return "";
}

const AUTH0_ENABLED = process.env.NEXT_PUBLIC_AUTH0_ENABLED === "true";

export function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  }
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function formatDuration(startMs: number, endMs: number): string {
  return `${formatTimestamp(startMs)} - ${formatTimestamp(endMs)}`;
}

export function isAuthRequired(): boolean {
  return AUTH0_ENABLED;
}

/**
 * Coerce a FastAPI/Pydantic ``detail`` field into a human-readable string.
 *
 * Backends return ``detail`` in three shapes:
 *   * ``string`` — Starlette/HTTPException; pass through verbatim.
 *   * ``Array<{msg, loc, type, ...}>`` — Pydantic 422 validation errors;
 *     join the ``msg`` fields so the operator sees actual messages
 *     instead of ``[object Object],[object Object]`` (which is what
 *     ``new Error(arr).message`` produces via ``Array#toString``).
 *   * any other object — fall back to ``JSON.stringify`` so at least
 *     the keys are visible.
 *
 * When ``detail`` is null/undefined/empty, returns ``fallback`` (callers
 * pass a context-specific message like ``"Render submission failed (422)"``).
 */
export function formatErrorDetail(detail: unknown, fallback: string): string {
  if (detail == null) return fallback;
  if (typeof detail === "string") return detail || fallback;
  if (Array.isArray(detail)) {
    if (detail.length === 0) return fallback;
    const parts = detail.map((e) => {
      if (typeof e === "string") return e;
      if (e && typeof e === "object") {
        const msg = (e as Record<string, unknown>).msg;
        if (typeof msg === "string" && msg) return msg;
        const loc = (e as Record<string, unknown>).loc;
        if (Array.isArray(loc) && loc.length > 0) {
          // ``msg`` is guaranteed non-usable here (the usable-string case
          // returned above), so don't interpolate it — a non-string msg
          // would render "undefined"/a number. Use a stable label.
          return `validation error at ${loc.join(".")}`;
        }
        return JSON.stringify(e);
      }
      return String(e);
    });
    return parts.join(", ");
  }
  if (typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return String(detail) || fallback;
}
