"use client";

import { AutoClipCard } from "./AutoClipCard";
import { EmptyState } from "./EmptyState";
import type { AutoSelectResponse, ScoringModeRequest } from "@/lib/types";

interface AutoSelectPreviewProps {
  videoId: string;
  selection: AutoSelectResponse | null;
  mode: ScoringModeRequest;
  isLoading: boolean;
  /** Per-clip render callback. Fires the single-clip render flow. */
  onRenderClip: (clipSceneIds: string[]) => void;
  /** Build the editor-deep-link URL for one clip's scene_ids. */
  buildEditorHref: (clipSceneIds: string[]) => string;
  /** True while ANY clip is in-flight for render. Disables all render buttons. */
  isRendering: boolean;
}

export function AutoSelectPreview({
  videoId,
  selection,
  mode,
  isLoading,
  onRenderClip,
  buildEditorHref,
  isRendering,
}: AutoSelectPreviewProps) {
  if (isLoading) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-[320px] items-center justify-center rounded-xl border border-gray-200 bg-white"
      >
        <div className="flex flex-col items-center gap-3 text-sm text-gray-500">
          <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-indigo-500" />
          <span>하이라이트 장면을 분석하고 있어요...</span>
        </div>
      </div>
    );
  }

  if (!selection) {
    return null;
  }

  if (selection.clips.length === 0) {
    return <EmptyState reason={selection.skipped_reason} mode={mode} />;
  }

  const totalSeconds = Math.round(selection.total_duration_ms / 1000);
  const scorer = selection.scorer ?? "pure";
  return (
    <section aria-label="자동 생성된 쇼츠 미리보기" className="space-y-4">
      <div className="flex items-center justify-between px-1">
        <h2 className="flex items-center gap-2 text-sm font-medium text-gray-700">
          {selection.clips.length}개 클립 · 총 {totalSeconds}초
          {scorer === "llm" && (
            <span
              className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700"
              title="AI가 캡션과 STT를 분석해 장면을 골랐습니다"
              aria-label="AI 자동 선택"
            >
              AI 선택
            </span>
          )}
        </h2>
        <p className="text-xs text-gray-500">
          각 클립을 개별 쇼츠로 렌더링하거나 편집할 수 있어요.
        </p>
      </div>
      <div className="grid gap-3">
        {selection.clips.map((clip, i) => (
          <AutoClipCard
            key={clip.scene_ids.join("-")}
            index={i}
            clip={clip}
            videoId={videoId}
            onRender={() => onRenderClip(clip.scene_ids)}
            editorHref={buildEditorHref(clip.scene_ids)}
            isRendering={isRendering}
          />
        ))}
      </div>
    </section>
  );
}
