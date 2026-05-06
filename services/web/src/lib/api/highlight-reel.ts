import { getApiBaseUrl } from "./utils";

type TokenGetter = () => Promise<string | null>;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HighlightClipPreview {
  video_id: string;
  video_title: string | null;
  scene_id: string;
  start_ms: number;
  end_ms: number;
  timeline_start_ms: number;
  duration_ms: number;
  run_scene_count: number;
}

export interface HighlightReelPreviewResponse {
  person_cluster_id: string;
  clips: HighlightClipPreview[];
  total_duration_ms: number;
  videos_used: number;
  videos_available: number;
  videos_excluded: number;
}

// Mirror of services/api/app/modules/shorts_render/schemas.py::RenderJobResponse.
// Memory: feedback_frontend_types_mirror_backend_schema.md — adding a field
// here without copying it from schemas.py is a regression vector.
export interface RenderJobResponse {
  id: string;
  video_id: string;
  title: string | null;
  status: string;
  created_at: string;
  completed_at: string | null;
  render_time_ms: number | null;
  output_duration_ms: number | null;
  output_size_bytes: number | null;
  error: string | null;
  download_url: string | null;
  thumbnail_video_id: string | null;
  thumbnail_scene_id: string | null;
  // Refinement chain (migration 056 / PR 5 of whisper subtitles).
  // - replaced_by_render_job_id: forward pointer to a refined child render.
  //   The wizard polls this and follows the chain to swap to the refined
  //   download_url silently.
  // - refined_from_render_job_id: back pointer on a child to its parent.
  // - refinement_source: 'whisper' | 'manual_edit' | null. 'manual_edit'
  //   prevents future automatic refinement passes.
  replaced_by_render_job_id: string | null;
  refined_from_render_job_id: string | null;
  refinement_source: string | null;
}

// Subset of heimdex_media_contracts.composition.SubtitleSpec sent by the
// frontend when an operator edits subtitles. Backend re-validates as the
// full SubtitleSpec — extra fields like ``style`` and ``template_id`` flow
// through unchanged when callers include them.
export interface SubtitleEdit {
  text: string;
  start_ms: number;
  end_ms: number;
  template_id?: string | null;
  style?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function generateHighlightPreview(
  personClusterId: string,
  targetDurationS: number,
  getToken: TokenGetter,
): Promise<HighlightReelPreviewResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }

  const res = await fetch(
    `${getApiBaseUrl()}/api/people/${personClusterId}/highlight-reel/preview`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({ target_duration_s: targetDurationS }),
    },
  );

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Preview failed (${res.status})`);
  }

  return res.json();
}

export async function getRenderJobStatus(
  jobId: string,
  getToken: TokenGetter,
): Promise<RenderJobResponse> {
  const headers: Record<string, string> = {};
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }

  const res = await fetch(
    `${getApiBaseUrl()}/api/shorts/render/${jobId}`,
    { method: "GET", headers },
  );

  if (!res.ok) {
    throw new Error(`Status check failed (${res.status})`);
  }

  return res.json();
}

/**
 * Replace a render job's subtitles and lock out automatic Whisper
 * refinement (the API sets ``refinement_source='manual_edit'``).
 *
 * Backend endpoint: ``PATCH /api/shorts/render/{job_id}/subtitles``
 * (PR 5 of the whisper-subtitles plan). Distinct from the title
 * PATCH per CLAUDE.md "single-field schema; do NOT widen".
 *
 * Manual edits are sticky — even if the operator later clears the
 * subtitles, the flag remains so a future Whisper pass doesn't
 * repopulate them. To re-enable automatic refinement, the operator
 * must trigger a fresh render (post creates a new row with a clean
 * ``refinement_source``).
 */
export async function patchRenderJobSubtitles(
  jobId: string,
  subtitles: SubtitleEdit[],
  getToken: TokenGetter,
): Promise<RenderJobResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }

  const res = await fetch(
    `${getApiBaseUrl()}/api/shorts/render/${jobId}/subtitles`,
    {
      method: "PATCH",
      headers,
      body: JSON.stringify({ subtitles }),
    },
  );

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Subtitle update failed (${res.status})`);
  }

  return res.json();
}

export async function submitHighlightRender(
  personClusterId: string,
  clips: HighlightClipPreview[],
  title: string | null,
  getToken: TokenGetter,
): Promise<RenderJobResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  try {
    const token = await getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } catch { /* noop */ }

  const res = await fetch(
    `${getApiBaseUrl()}/api/people/${personClusterId}/highlight-reel/render`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({ clips, title }),
    },
  );

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Render failed (${res.status})`);
  }

  return res.json();
}
