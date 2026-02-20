const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

type TokenGetter = () => Promise<string | null>;

export interface CloudExportRequest {
  project_name: string;
  frame_rate: number;
  clips: {
    video_id: string;
    clip_name: string;
    start_ms: number;
    end_ms: number;
  }[];
}

export interface CloudExportResult {
  clip_count: number;
  unresolved_clips: string[];
  filename: string;
}

export async function exportEdlCloud(
  request: CloudExportRequest,
  getToken?: TokenGetter,
): Promise<CloudExportResult> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (getToken) {
    try {
      const token = await getToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    } catch {
      // proceed without auth
    }
  }

  const response = await fetch(`${API_BASE_URL}/api/export/edl`, {
    method: "POST",
    headers,
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Export failed (${response.status})`);
  }

  const blob = await response.blob();
  const clipCount = parseInt(response.headers.get("X-Clip-Count") ?? "0", 10);
  const unresolvedRaw = response.headers.get("X-Unresolved-Clips") ?? "";
  const unresolved = unresolvedRaw ? unresolvedRaw.split(",") : [];

  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
  const filename = filenameMatch?.[1] ?? `${request.project_name}.edl`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);

  return {
    clip_count: clipCount,
    unresolved_clips: unresolved,
    filename,
  };
}
