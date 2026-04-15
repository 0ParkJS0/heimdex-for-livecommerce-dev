/**
 * Dedicated blur detail page. Mounted at ``/videos/[videoId]/blur``.
 *
 * Responsibilities:
 *   1. Resolve the most recent blur job for the given video (via the
 *      list endpoint) and drive every other section off it.
 *   2. While the job is running, render a progress bar sourced from
 *      the heartbeat endpoint (``progress_pct``, ``phase``).
 *   3. When the job is done, let the user toggle between the original
 *      and blurred MP4 in a native ``<video>`` element, render a
 *      timeline of detections by category (SVG lanes) fetched from the
 *      presigned manifest URL, and expose a ProRes 4444 layer export
 *      panel with category checkboxes + live export progress +
 *      download link.
 *   4. All sub-components are co-located to keep Phase 5 reviewable as
 *      a single surface.
 *
 * This page does NOT render before the blur subsystem is ready: it
 * assumes the caller already holds a blur job id (from
 * VideoDetailPage), and 404s gracefully if the feature flag is off.
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  BlurCategory,
  BlurExportFormat,
  BlurJobResponse,
  buildBlurExportDownloadHref,
  createBlurExport,
} from "@/lib/api/blur";
import { useBlurExport, useBlurJob, useBlurJobsForFile } from "@/features/blur/hooks/useBlurJob";
import { useAuth } from "@/lib/auth";

// ---------- shared types sourced from the manifest JSON on S3 ----------

interface BlurManifestDetection {
  frame_idx: number;
  t_ms: number;
  category: string;
  label: string;
  confidence: number;
  bbox_norm: [number, number, number, number];
  from_cache: boolean;
}

interface BlurManifest {
  schema_version: string;
  video: { fps: number; width: number; height: number; frame_count: number };
  summary: Record<string, number>;
  detections: BlurManifestDetection[];
  mask_s3_keys: Record<string, string> | null;
}

// ---------- korean labels (co-located, no i18n lib on this repo) ----------

const CATEGORY_LABELS: Record<string, string> = {
  face: "얼굴",
  license_plate: "번호판",
  card_object: "신용카드",
  logo: "로고",
  object: "기타",
};

const PHASE_LABELS: Record<string, string> = {
  queued: "대기 중",
  initializing: "모델 준비 중",
  detecting: "검출 중",
  encoding: "인코딩 중",
  uploading: "업로드 중",
  finalizing: "마무리 중",
};

const STATUS_BADGE_CLASS: Record<string, string> = {
  queued: "bg-yellow-100 text-yellow-800",
  running: "bg-blue-100 text-blue-800",
  done: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-gray-100 text-gray-700",
};

function formatTime(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ============================================================================
// useBlurManifest — fetches the presigned manifest URL JSON
// ============================================================================

function useBlurManifest(url: string | null): {
  manifest: BlurManifest | null;
  loading: boolean;
  error: Error | null;
} {
  const [manifest, setManifest] = useState<BlurManifest | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(url));
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!url) {
      setManifest(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`manifest fetch failed (${res.status})`);
        return res.json();
      })
      .then((data) => {
        if (cancelled) return;
        setManifest(data as BlurManifest);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  return { manifest, loading, error };
}

// ============================================================================
// BlurHeader
// ============================================================================

function BlurHeader({
  videoId,
  job,
}: {
  videoId: string;
  job: BlurJobResponse | null;
}) {
  const status = job?.status ?? "queued";
  const badgeClass = STATUS_BADGE_CLASS[status] ?? "bg-gray-100 text-gray-700";

  return (
    <div className="mb-4 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <Link
          href={`/videos/${videoId}`}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          ← 영상 상세로
        </Link>
        <h1 className="text-xl font-semibold text-gray-900">블러 처리</h1>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${badgeClass}`}>
          {status}
        </span>
      </div>
    </div>
  );
}

// ============================================================================
// BlurPlayer — swaps video src between original and blurred
// ============================================================================

function BlurPlayer({
  job,
}: {
  job: BlurJobResponse;
}) {
  // Default to blurred-on when a done job exists. Persist the user's
  // last choice in localStorage so re-opening the page stays sticky.
  const storageKey = `heimdex_blur_view_${job.id}`;
  const [blurOn, setBlurOn] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    const stored = window.localStorage.getItem(storageKey);
    return stored == null ? true : stored === "1";
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(storageKey, blurOn ? "1" : "0");
  }, [blurOn, storageKey]);

  const src = blurOn ? job.blurred_playback_url : null;
  const hasBlurred = Boolean(job.blurred_playback_url);

  return (
    <div className="rounded-xl border border-gray-200 bg-black">
      {src ? (
        <video
          key={src}
          src={src}
          controls
          playsInline
          className="h-auto w-full rounded-t-xl"
        />
      ) : (
        <div className="flex aspect-video items-center justify-center rounded-t-xl bg-gray-900 text-gray-400">
          {hasBlurred
            ? "블러 OFF 상태에서 원본 재생은 영상 상세 페이지에서 확인해주세요."
            : "블러 결과를 불러올 수 없습니다."}
        </div>
      )}
      <div className="flex items-center justify-between gap-3 rounded-b-xl bg-white p-3">
        <div className="text-sm text-gray-700">
          {blurOn ? "블러 적용 중" : "블러 해제됨"}
        </div>
        <button
          type="button"
          onClick={() => setBlurOn((v) => !v)}
          disabled={!hasBlurred}
          className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          {blurOn ? "블러 끄기" : "블러 켜기"}
        </button>
      </div>
    </div>
  );
}

// ============================================================================
// BlurProgressPanel
// ============================================================================

function BlurProgressPanel({ job }: { job: BlurJobResponse }) {
  const pct = Math.max(0, Math.min(100, job.progress_pct ?? 0));
  const phaseLabel = job.phase ? PHASE_LABELS[job.phase] ?? job.phase : "처리 대기";

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
      <div className="flex items-center justify-between text-sm font-medium text-blue-900">
        <span>{phaseLabel}</span>
        <span>{pct}%</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-blue-100">
        <div
          className="h-full rounded-full bg-blue-600 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-blue-700">
        모델 추론과 인코딩이 진행 중입니다. 몇 분 정도 걸릴 수 있습니다.
      </p>
    </div>
  );
}

// ============================================================================
// BlurTimeline — SVG lanes, one per category
// ============================================================================

function BlurTimeline({ manifest }: { manifest: BlurManifest }) {
  // Group detections by category in source order.
  const { lanes, totalMs } = useMemo(() => {
    const byCategory: Record<string, BlurManifestDetection[]> = {};
    for (const d of manifest.detections) {
      (byCategory[d.category] ||= []).push(d);
    }
    const durationMs = manifest.video.frame_count > 0
      ? Math.round((manifest.video.frame_count * 1000) / manifest.video.fps)
      : 0;
    return {
      lanes: Object.entries(byCategory),
      totalMs: durationMs || 1,
    };
  }, [manifest]);

  if (lanes.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-4 text-sm text-gray-500">
        검출된 영역이 없습니다.
      </div>
    );
  }

  const width = 800;
  const laneHeight = 32;
  const laneGap = 8;
  const height = lanes.length * (laneHeight + laneGap);

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-gray-900">검출 타임라인</h3>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-w-[600px]">
        {lanes.map(([category, detections], laneIdx) => {
          const y = laneIdx * (laneHeight + laneGap);
          const label = CATEGORY_LABELS[category] ?? category;
          return (
            <g key={category}>
              <rect x={0} y={y} width={width} height={laneHeight} rx={4} fill="#F3F4F6" />
              <text x={8} y={y + laneHeight / 2 + 4} fontSize={11} fill="#374151">
                {label} ({detections.length})
              </text>
              {detections.map((d, i) => {
                const cx = 90 + ((d.t_ms / totalMs) * (width - 100));
                return (
                  <rect
                    key={`${category}-${i}`}
                    x={cx - 1}
                    y={y + 4}
                    width={2}
                    height={laneHeight - 8}
                    fill="#2563EB"
                  >
                    <title>
                      {label} · {formatTime(d.t_ms)} · {(d.confidence * 100).toFixed(0)}%
                    </title>
                  </rect>
                );
              })}
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
        <span>0:00</span>
        <span>{formatTime(totalMs)}</span>
      </div>
    </div>
  );
}

// ============================================================================
// BlurCategoryStats — per-category counts
// ============================================================================

function BlurCategoryStats({ summary }: { summary: Record<string, number> }) {
  const entries = Object.entries(summary).filter(([, n]) => n > 0);
  if (entries.length === 0) {
    return null;
  }
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-gray-900">카테고리별 검출 수</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {entries.map(([category, count]) => (
          <div key={category} className="rounded-lg bg-gray-50 p-3">
            <div className="text-xs text-gray-500">
              {CATEGORY_LABELS[category] ?? category}
            </div>
            <div className="mt-1 text-lg font-semibold text-gray-900">{count}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// BlurExportPanel — category checkboxes + submit + live export progress
// ============================================================================

function BlurExportPanel({
  jobId,
  availableCategories,
}: {
  jobId: string;
  availableCategories: string[];
}) {
  const { getAccessToken } = useAuth();
  const [selected, setSelected] = useState<Record<string, boolean>>(() => {
    const m: Record<string, boolean> = {};
    for (const c of availableCategories) m[c] = true;
    return m;
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [exportId, setExportId] = useState<string | null>(null);

  const exportState = useBlurExport(exportId);

  const anySelected = availableCategories.some((c) => selected[c]);

  const handleSubmit = useCallback(async () => {
    const categories = availableCategories.filter((c) => selected[c]) as BlurCategory[];
    if (categories.length === 0) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await createBlurExport(jobId, categories, "prores_4444" as BlurExportFormat, getAccessToken);
      setExportId(res.id);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }, [availableCategories, jobId, selected, getAccessToken]);

  const exp = exportState.data;
  const isActive = exp && (exp.status === "queued" || exp.status === "running");
  const isDone = exp && exp.status === "done";
  const isFailed = exp && exp.status === "failed";

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-gray-900">
        NLE 레이어 내보내기 (ProRes 4444)
      </h3>
      <p className="mb-3 text-xs text-gray-500">
        선택한 카테고리만 포함된 알파 레이어 ``.mov``를 생성합니다.
        Premiere / DaVinci / FCP에서 원본 위에 올려 추가 편집하세요.
      </p>

      <div className="space-y-2">
        {availableCategories.map((category) => (
          <label key={category} className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-gray-300 text-blue-600"
              checked={selected[category] ?? false}
              onChange={() => setSelected((prev) => ({ ...prev, [category]: !prev[category] }))}
              disabled={submitting || Boolean(isActive)}
            />
            {CATEGORY_LABELS[category] ?? category}
          </label>
        ))}
      </div>

      {submitError && (
        <div className="mt-3 rounded-lg bg-red-50 p-2 text-xs text-red-800">{submitError}</div>
      )}

      <div className="mt-4 flex items-center justify-between">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitting || !anySelected || Boolean(isActive)}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {submitting ? "전송 중..." : "내보내기 시작"}
        </button>
        {isActive && (
          <span className="text-xs text-blue-700">내보내기 진행 중...</span>
        )}
        {isDone && (
          <a
            href={buildBlurExportDownloadHref(exp!.id)}
            download
            className="rounded-lg border border-green-500 bg-green-50 px-3 py-1.5 text-xs font-medium text-green-800 hover:bg-green-100"
          >
            ⬇ 레이어 다운로드
          </a>
        )}
        {isFailed && (
          <span className="text-xs text-red-700">내보내기 실패: {exp!.error ?? "알 수 없는 오류"}</span>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// BlurDetailPage — top-level container
// ============================================================================

export interface BlurDetailPageProps {
  videoId: string;
}

export function BlurDetailPage({ videoId }: BlurDetailPageProps) {
  const router = useRouter();
  // First resolve the latest blur job for this video. The list
  // endpoint is org-scoped; we pick the most recent by requested_at.
  // NB: this page uses the drive file id as ``videoId`` in the URL
  // — matching how VideoDetailPage passes it around. The blur API is
  // keyed by file_id, so we use videoId as file_id.
  const { data: list, loading: listLoading, disabled, error: listError } = useBlurJobsForFile(videoId);

  const latestJobId = useMemo(() => {
    if (!list || list.items.length === 0) return null;
    // List endpoint is already ordered by requested_at DESC.
    return list.items[0].id;
  }, [list]);

  const { data: job, loading: jobLoading, error: jobError } = useBlurJob(latestJobId);
  const { manifest } = useBlurManifest(job?.manifest_url ?? null);

  // Redirect back to the video if the feature is disabled on this env.
  useEffect(() => {
    if (disabled) {
      router.replace(`/videos/${videoId}`);
    }
  }, [disabled, router, videoId]);

  if (listLoading || jobLoading) {
    return (
      <div className="mx-auto max-w-5xl p-6 text-sm text-gray-500">
        블러 작업을 불러오는 중...
      </div>
    );
  }

  if (listError || jobError) {
    return (
      <div className="mx-auto max-w-5xl p-6">
        <BlurHeader videoId={videoId} job={null} />
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-800">
          블러 작업을 불러올 수 없습니다: {(listError ?? jobError)?.message}
        </div>
      </div>
    );
  }

  if (!latestJobId || !job) {
    return (
      <div className="mx-auto max-w-5xl p-6">
        <BlurHeader videoId={videoId} job={null} />
        <div className="rounded-lg border border-gray-200 bg-white p-6 text-sm text-gray-600">
          이 영상에 대한 블러 작업이 없습니다. 영상 상세 페이지에서 "블러 처리"를 시작해 주세요.
        </div>
      </div>
    );
  }

  const isActive = job.status === "queued" || job.status === "running";
  const isDone = job.status === "done";
  const availableCategories = job.mask_s3_keys ? Object.keys(job.mask_s3_keys) : [];

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <BlurHeader videoId={videoId} job={job} />

      {isActive && <BlurProgressPanel job={job} />}

      {isDone && <BlurPlayer job={job} />}

      {isDone && job.detections_summary && (
        <BlurCategoryStats summary={job.detections_summary} />
      )}

      {isDone && manifest && <BlurTimeline manifest={manifest} />}

      {isDone && availableCategories.length > 0 && (
        <BlurExportPanel jobId={job.id} availableCategories={availableCategories} />
      )}

      {job.status === "failed" && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          블러 작업이 실패했습니다: {job.error ?? "알 수 없는 오류"}
        </div>
      )}
    </div>
  );
}
