const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL;

if (!API_BASE_URL) {
  console.error(
    "[Heimdex] NEXT_PUBLIC_API_URL is not set. " +
    "API calls will fail. Set it to http://{org}.app.heimdex.local:8000"
  );
}

if (API_BASE_URL?.includes("localhost")) {
  console.warn(
    "[Heimdex] WARNING: NEXT_PUBLIC_API_URL points to localhost. " +
    "This bypasses multi-tenancy! Use http://{org}.app.heimdex.local:8000 instead."
  );
}

export interface SearchFilters {
  date_from?: string;
  date_to?: string;
  source_types?: ("gdrive" | "removable_disk")[];
  library_ids?: string[];
  person_cluster_ids?: string[];
}

export interface SearchRequest {
  q: string;
  alpha: number;
  filters: SearchFilters;
}

export interface DebugInfo {
  lexical_rank: number | null;
  lexical_score: number | null;
  vector_rank: number | null;
  vector_score: number | null;
  fused_score: number;
}

export interface SegmentResult {
  segment_id: string;
  video_id: string;
  library_id: string;
  library_name: string;
  start_ms: number;
  end_ms: number;
  snippet: string;
  thumbnail_url: string | null;
  source_type: "gdrive" | "removable_disk";
  required_drive_nickname: string | null;
  capture_time: string | null;
  people_cluster_ids: string[];
  debug: DebugInfo;
}

export interface FacetItem {
  value: string;
  count: number;
  label: string | null;
}

export interface Facets {
  libraries: FacetItem[];
  source_types: FacetItem[];
  people_cluster_ids: FacetItem[];
}

export interface SearchResponse {
  results: SegmentResult[];
  total_candidates: number;
  facets: Facets;
  query: string;
  alpha: number;
}

export async function search(request: SearchRequest): Promise<SearchResponse> {
  if (!API_BASE_URL) {
    throw new Error(
      "NEXT_PUBLIC_API_URL is not configured. " +
      "Set it to http://{org}.app.heimdex.local:8000"
    );
  }

  const response = await fetch(`${API_BASE_URL}/api/search`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `Search failed: ${response.status}`);
  }

  return response.json();
}

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
