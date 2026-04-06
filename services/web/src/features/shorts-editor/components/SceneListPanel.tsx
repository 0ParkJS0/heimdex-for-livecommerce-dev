"use client";

import { useMemo } from "react";
import type { VideoScene } from "@/lib/types";
import type { EditorClip } from "../lib/types";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { cn } from "@/lib/utils";

interface SceneListPanelProps {
  videoId: string;
  scenes: VideoScene[];
  clips: EditorClip[];
  selectedClipIndex: number | null;
  onToggleScene: (scene: VideoScene) => void;
  onSelectClip: (index: number) => void;
}

function formatTime(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function SceneListPanel({
  videoId,
  scenes,
  clips,
  selectedClipIndex,
  onToggleScene,
  onSelectClip,
}: SceneListPanelProps) {
  const clipSceneIds = useMemo(
    () => new Set(clips.map((c) => c.sceneId)),
    [clips],
  );

  const clipIndexBySceneId = useMemo(() => {
    const map = new Map<string, number>();
    clips.forEach((c, i) => map.set(c.sceneId, i));
    return map;
  }, [clips]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-900">장면 목록</h3>
        <span className="text-xs text-gray-400">{scenes.length}개 장면</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {scenes.map((scene, i) => {
          const isActive = clipSceneIds.has(scene.scene_id);
          const clipIdx = clipIndexBySceneId.get(scene.scene_id);
          const isSelected = isActive && clipIdx != null && clipIdx === selectedClipIndex;

          return (
            <button
              key={scene.scene_id}
              type="button"
              onClick={() => {
                if (isActive && clipIdx != null) {
                  onSelectClip(clipIdx);
                } else {
                  onToggleScene(scene);
                }
              }}
              className={cn(
                "w-full text-left border-b border-gray-100 p-3 transition-colors hover:bg-gray-50",
                isActive && "border-l-3 border-l-indigo-500 bg-indigo-50/50",
                isSelected && "bg-indigo-100/70 ring-1 ring-inset ring-indigo-300",
              )}
            >
              <div className="flex items-start gap-3">
                <div className="flex-shrink-0 w-16 h-10 rounded overflow-hidden bg-gray-200">
                  <SceneThumbnail
                    videoId={videoId}
                    sceneId={scene.scene_id}
                    agentAvailable={false}
                    className="w-full h-full"
                    sourceType="gdrive"
                  />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium text-gray-700">
                      장면 {i + 1}
                    </span>
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-gray-400 font-mono">
                        {formatTime(scene.start_ms)} - {formatTime(scene.end_ms)}
                      </span>
                      {isActive && (
                        <svg className="w-4 h-4 text-indigo-600" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                        </svg>
                      )}
                    </div>
                  </div>

                  {scene.transcript_raw && (
                    <p className="text-xs text-gray-500 line-clamp-2 mb-1.5">
                      {scene.transcript_raw}
                    </p>
                  )}

                  {scene.scene_caption && !scene.transcript_raw && (
                    <p className="text-xs text-gray-400 italic line-clamp-2 mb-1.5">
                      {scene.scene_caption}
                    </p>
                  )}

                  {(scene.keyword_tags.length > 0 || (scene.ai_tags && scene.ai_tags.length > 0)) && (
                    <div className="flex flex-wrap gap-1">
                      {scene.keyword_tags.slice(0, 3).map((tag) => (
                        <span
                          key={tag}
                          className="inline-block rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] text-indigo-700"
                        >
                          {tag}
                        </span>
                      ))}
                      {scene.ai_tags?.slice(0, 2).map((tag) => (
                        <span
                          key={tag}
                          className="inline-block rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] text-emerald-700"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </button>
          );
        })}

        {scenes.length === 0 && (
          <div className="flex items-center justify-center p-8 text-gray-400">
            <p className="text-xs">장면 정보를 불러올 수 없습니다</p>
          </div>
        )}
      </div>
    </div>
  );
}
