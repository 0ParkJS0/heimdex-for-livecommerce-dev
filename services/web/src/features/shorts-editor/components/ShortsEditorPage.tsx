"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { getAllVideoScenes } from "@/lib/api/videos";
import { getShortComposition } from "@/lib/api/shorts-render";
import type { VideoScenesResponse } from "@/lib/types";
import {
  useTopHeaderActions,
  useTopHeaderBack,
  useTopHeaderLeftActions,
} from "@/components/layout/TopHeaderActionsContext";
import { cn } from "@/lib/utils";
import { useEditorState, createClipFromScene, generateSubtitlesFromTranscript } from "../hooks/useEditorState";
import { useEditorKeyboard } from "../hooks/useEditorKeyboard";
import { STARTER_TEMPLATES } from "../lib/starter-templates";
import {
  wireSubtitleToEditorSubtitle,
} from "../lib/wire-to-editor";
import { recomputeTimeline } from "../lib/timeline-math";
import { useCompositionExport } from "../hooks/useCompositionExport";
import type { RenderStatus } from "../hooks/useCompositionExport";
import { buildCompositionPayloadFromState, usePresets } from "../hooks/usePresets";
import { EditorLayout } from "./EditorLayout";
import { FullscreenOverlay } from "./FullscreenOverlay";
import { PreviewPanel } from "./PreviewPanel";
import { TimelinePanel } from "./TimelinePanel";
import { OverlayPanel } from "./OverlayPanel";
import { SubtitleListNav } from "./SubtitleEditor";
import { TemplateSaveDialog } from "./TemplateSaveDialog";
import { TemplateSaveMenu } from "./TemplateSaveMenu";
import type { EditorSubtitle } from "../lib/types";
import { getVisibleSubtitles } from "../lib/source-time";
import type { EditorOverlay, EditorTextOverlay } from "../lib/overlay-types";
import { RightPanel } from "./RightPanel";
import { BackgroundPanel } from "./BackgroundPanel";
import { TemplatePanel } from "./TemplatePanel";

function BackArrowIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
    </svg>
  );
}

// 2026-05-19 — idle label flipped from "내보내기" to "저장하기" so the
// editor button reads as a save action ("write this composition to my
// saved-shorts list") rather than a delivery action. The behavior is
// unchanged — submitComposition still triggers the render pipeline
// and the resulting short shows up on /export/shorts via the
// existing polling path. The download affordance now lives on the
// saved-shorts list itself.
const RENDER_STATUS_LABELS: Record<RenderStatus, string> = {
  idle: "저장하기",
  submitting: "제출 중...",
  queued: "대기 중...",
  rendering: "렌더링 중...",
  completed: "완료",
  failed: "실패",
  rate_limited: "요청 제한",
};

export function ShortsEditorPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { getAccessToken } = useAuth();

  const videoId = searchParams.get("videoId") ?? "";
  const sceneIdsParam = searchParams.get("sceneIds") ?? "";
  const shortId = searchParams.get("shortId") ?? "";
  // 2026-05-19 — `?preview=1` is set by SavedShortsPage when the
  // operator clicks the thumbnail (vs the menu's [편집]). It signals
  // "show me the fullscreen preview, not the edit chrome", so the
  // editor auto-opens FullscreenOverlay once the composition lands.
  // Closing the overlay drops back into the regular editor; that's
  // intentional so the operator can switch from "watch" to "edit"
  // without re-navigating.
  const previewOnEntry = searchParams.get("preview") === "1";

  const [meta, setMeta] = useState<VideoScenesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [isFullscreen, setIsFullscreen] = useState(false);
  // One-shot guard for the `?preview=1` auto-open below. Without it,
  // closing the fullscreen overlay then toggling some state that
  // re-runs the effect would re-open the overlay and pin the operator
  // in preview mode.
  const [didAutoOpenPreview, setDidAutoOpenPreview] = useState(false);
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  // Playback rate derived from the state machine; the operator changes
  // it via the SpeedPopover which dispatches SET_RATE.
  // figma: 1670:185907 — 마스터 볼륨 (하단 컨트롤 슬라이더와 동기화)
  const [masterVolume, setMasterVolume] = useState(1.0);
  // L9 / T9 — transient drop-target hint. Auto-clears after ~2.4 sec
  // so the operator gets feedback without permanent UI chrome.
  const [dropHint, setDropHint] = useState<string | null>(null);
  useEffect(() => {
    if (!dropHint) return;
    const t = setTimeout(() => setDropHint(null), 2400);
    return () => clearTimeout(t);
  }, [dropHint]);

  const editor = useEditorState();
  const {
    state,
    initFromScenes,
    initFromComposition,
    setPlayhead,
    setPlaying,
    selectSubtitle,
    updateSubtitle,
    undo,
    redo,
  } = editor;

  // Ctrl+Z / Cmd+Z rolls back the most recent drag-style gesture; the
  // Shift variant (Ctrl+Shift+Z / Cmd+Shift+Z) re-applies the previously
  // undone gesture by walking the redo stack. Both are skipped when the
  // focused element is a text input so typing into a subtitle / preset
  // name doesn't get hijacked.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const meta = e.ctrlKey || e.metaKey;
      if (!meta || e.altKey) return;
      if (e.key !== "z" && e.key !== "Z") return;
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      const isEditable =
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        target?.isContentEditable === true;
      if (isEditable) return;
      e.preventDefault();
      if (e.shiftKey) {
        redo();
      } else {
        undo();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [undo, redo]);

  const {
    renderStatus,
    renderJob,
    renderError,
    submitComposition,
    reset: resetRender,
  } = useCompositionExport({
    state,
    title,
    getToken: getAccessToken,
  });

  const handleSubtitlePositionChange = useCallback(
    (index: number, positionX: number, positionY: number) => {
      const sub = state.subtitles[index];
      if (!sub) return;
      updateSubtitle(index, {
        style: { ...sub.style, positionX, positionY },
      });
    },
    [state.subtitles, updateSubtitle],
  );

  const handleSubtitleFontSizeChange = useCallback(
    (index: number, fontSizePx: number) => {
      const sub = state.subtitles[index];
      if (!sub) return;
      updateSubtitle(index, {
        style: { ...sub.style, fontSizePx },
      });
    },
    [state.subtitles, updateSubtitle],
  );

  // ---------------------------------------------------------------------
  // V2 timeline bridge
  // ---------------------------------------------------------------------
  // Timeline data model — V2 (the only path since the 2026-05-22 cleanup):
  //   • Host auto-STT subtitles live in ``state.subtitles`` → bottom
  //     subtitle track.
  //   • Operator-added text overlays live in ``state.overlays`` → upper
  //     overlay tracks (one row per overlay).
  //   • Background overlays are deliberately NOT shown on the timeline;
  //     they live on the canvas and are managed via the right panel.
  const textOverlays = useMemo(
    () =>
      state.overlays.filter(
        (o): o is EditorTextOverlay => o.kind === "text",
      ),
    [state.overlays],
  );

  const timelineSubtitles: EditorSubtitle[] = getVisibleSubtitles(state.subtitles, state.clips);

  const timelineTextOverlays: (EditorSubtitle & { layerIndex: number })[] = useMemo(() => {
    return textOverlays.map((o) => ({
      id: o.id,
      text: o.text,
      startMs: o.startMs,
      endMs: o.endMs,
      // Carry layerIndex into the projection so TimelinePanel can
      // place each text overlay at its own row (layerIndex 0 = bottom).
      layerIndex: o.layerIndex,
      style: {
        fontFamily: o.fontFamily,
        fontSizePx: o.fontSizePx,
        fontColor: o.fontColor,
        fontWeight: o.fontWeight,
        positionX: o.transform.x,
        positionY: o.transform.y,
        backgroundColor: o.highlightColor,
        backgroundOpacity: o.highlightOpacity,
      },
    }));
  }, [textOverlays]);

  // Selection state for the (host) subtitle track is always the V1
  // index — the operator-added overlay track has its own selection
  // wiring via state.selectedOverlayId (Q7).
  const timelineSelectedSubtitleIndex: number | null =
    state.selectedSubtitleIndex;

  // Host auto-STT subtitles always live in state.subtitles (decision
  // 2026-05-22 — host subtitles are no longer routed into overlays
  // under V2). The stale V2 branches in these handlers used to dispatch
  // selectOverlay / updateOverlay / removeOverlay against host-subtitle
  // indices, which left state.selectedSubtitleIndex untouched and broke
  // the left SubtitleListNav's selected-border (and made the bottom
  // SubtitleTrack's trim/remove dispatch into the wrong array).
  const handleTimelineAddSubtitle = useCallback(
    (sub: EditorSubtitle) => editor.addSubtitle(sub),
    [editor],
  );

  const handleTimelineSelectSubtitle = useCallback(
    (index: number | null) => editor.selectSubtitle(index),
    [editor],
  );

  const handleTimelineUpdateSubtitle = useCallback(
    (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) =>
      editor.updateSubtitle(index, updates),
    [editor],
  );

  const handleTimelineRemoveSubtitle = useCallback(
    (index: number) => editor.removeSubtitle(index),
    [editor],
  );

  // GNB "템플릿 저장" entry — opens the same TemplateSaveDialog that the
  // PresetSection uses, but driven from the global header. Save targets the
  // currently selected overlay; menu is disabled when no overlay is selected.
  const selectedOverlay = useMemo<EditorOverlay | null>(() => {
    if (state.selectedOverlayId == null) return null;
    return state.overlays.find((o) => o.id === state.selectedOverlayId) ?? null;
  }, [state.selectedOverlayId, state.overlays]);

  // GNB '템플릿 저장' is now a COMPOSITION save (operator request
  // 2026-05-24) — it captures subtitle style + every operator overlay
  // + letterbox + video transform in one preset so the same canvas
  // chrome can be re-applied to a different video later. The legacy
  // per-overlay style save lives in PresetSection (right panel) and
  // continues to use ``presetsApi.save``.
  //
  // The TemplatePanel grid surfaces every preset (text + background +
  // composition) so the operator can pick any saved chrome from one
  // place. Passing ``kind: undefined`` to usePresets disables the
  // server-side filter and returns all kinds.
  const presetsApi = usePresets({
    kind: undefined,
    getToken: getAccessToken,
  });

  const handleTemplateSave = useCallback(
    async (name: string, isShared: boolean) => {
      // GNB save → composition snapshot. Always succeeds regardless of
      // whether an overlay is currently selected — the snapshot is the
      // global canvas, not the focused element.
      const payload = buildCompositionPayloadFromState(state);
      await presetsApi.saveComposition(name, payload, isShared);
      setTemplateDialogOpen(false);
    },
    [state, presetsApi],
  );

  // figma: 1602:37719 — editor GNB merges into the global TopHeader.
  // Back lives in the dedicated back slot, title/scene-count in the left
  // actions slot, render controls in the right actions slot.
  const handleHeaderBack = useCallback(() => {
    if (state.isDirty && !window.confirm("저장하지 않은 변경사항이 있습니다. 나가시겠습니까?")) {
      return;
    }
    router.push("/export/shorts");
  }, [router, state.isDirty]);

  const headerBackSlot = useMemo(
    () => ({ label: "뒤로가기", onClick: handleHeaderBack }),
    [handleHeaderBack],
  );
  useTopHeaderBack(headerBackSlot);

  const headerLeftSlot = useMemo(() => {
    if (isLoading || loadError) return null;
    // figma: 1669:48308 — title input + "N개 장면" pair, gap=10. The input
    // hugs its content so the "N개 장면" label sits ~10px to the right of
    // the last character with no extra dead space. ``size`` is set to the
    // visible character count (no +1 buffer) and we drop the lower bound
    // via inline width so short titles like "쇼츠1" don't reserve a
    // 60px-wide column. Long titles can grow to the safe ~640px cap.
    const placeholder = meta?.video_title ?? "제목 없음";
    const measureSource = title || placeholder;
    const sizeChars = Math.max(2, Math.min(measureSource.length, 60));
    return (
      <div className="flex items-center gap-[10px]">
        <input
          type="text"
          size={sizeChars}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={placeholder}
          aria-label="영상 제목"
          className="rounded-md border border-transparent px-1 text-[18px] font-semibold leading-[1.4] tracking-[-0.45px] text-black placeholder-grayscale-300 hover:border-grayscale-100 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
          style={{ maxWidth: "640px" }}
        />
        <span className="whitespace-nowrap text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-neutral-h-500">
          {state.clips.length}개 장면
        </span>
      </div>
    );
  }, [isLoading, loadError, title, meta?.video_title, state.clips.length, state.isDirty]);
  useTopHeaderLeftActions(headerLeftSlot);

  const isRenderWorking =
    renderStatus === "submitting" || renderStatus === "queued" || renderStatus === "rendering";
  const canRender =
    state.clips.length > 0 && !isRenderWorking && renderStatus !== "completed";

  const handleRenderDownload = useCallback(() => {
    if (!renderJob?.download_url) return;
    const a = document.createElement("a");
    a.href = renderJob.download_url;
    a.download = `short_${renderJob.id}.mp4`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }, [renderJob]);

  const headerRightSlot = useMemo(() => {
    if (isLoading || loadError) return null;
    // figma: 1602:37719 — right side buttons h=32 px=10 py=6 r=8 fs=12.
    return (
      <div className="flex items-center gap-2">
        {renderError && (
          <span className="max-w-48 truncate text-xs text-red-h-500">{renderError}</span>
        )}
        {/* GNB 템플릿 저장 — composition save (global chrome). No
            selection required; the snapshot is the whole canvas, not
            an individual overlay. */}
        <TemplateSaveMenu
          onClick={() => setTemplateDialogOpen(true)}
          disabled={false}
        />
        {renderStatus === "completed" && renderJob && (
          <>
            <button
              type="button"
              onClick={handleRenderDownload}
              className="inline-flex h-8 items-center gap-1.5 rounded-[8px] bg-heimdex-navy-500 px-[10px] py-[6px] text-[12px] font-semibold text-white transition-colors hover:bg-heimdex-navy-600"
            >
              <DownloadIcon />
              다운로드
            </button>
            <button
              type="button"
              onClick={resetRender}
              className="h-8 rounded-[8px] border border-neutral-h-500 bg-white px-[10px] py-[6px] text-[12px] font-semibold text-neutral-h-500 transition-colors hover:bg-grayscale-10"
            >
              다시 렌더링
            </button>
          </>
        )}
        {renderStatus === "failed" && (
          <button
            type="button"
            onClick={resetRender}
            className="h-8 rounded-[8px] border border-neutral-h-500 bg-white px-[10px] py-[6px] text-[12px] font-semibold text-neutral-h-500 transition-colors hover:bg-grayscale-10"
          >
            재시도
          </button>
        )}
        {renderStatus !== "completed" && (
          <button
            type="button"
            onClick={submitComposition}
            disabled={!canRender}
            className={cn(
              "inline-flex h-8 items-center gap-2 rounded-[8px] px-[10px] py-[6px] text-[12px] font-semibold leading-none transition-colors",
              canRender
                ? "bg-heimdex-navy-500 text-white hover:bg-heimdex-navy-600"
                : "cursor-not-allowed bg-neutral-h-100 text-neutral-h-300",
            )}
          >
            {isRenderWorking && (
              <div className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
            )}
            {RENDER_STATUS_LABELS[renderStatus]}
          </button>
        )}
      </div>
    );
  }, [
    isLoading,
    loadError,
    renderError,
    selectedOverlay,
    renderStatus,
    renderJob,
    handleRenderDownload,
    resetRender,
    submitComposition,
    canRender,
    isRenderWorking,
  ]);
  useTopHeaderActions(headerRightSlot);

  // Open fullscreen once the composition is ready when `?preview=1`
  // is in the URL. Gated on `state.clips.length > 0` so the overlay
  // never lands on an empty <video> element; the one-shot guard above
  // (didAutoOpenPreview) keeps closing-the-overlay from re-triggering.
  useEffect(() => {
    if (!previewOnEntry || didAutoOpenPreview) return;
    if (state.clips.length === 0 || isLoading) return;
    setIsFullscreen(true);
    setDidAutoOpenPreview(true);
  }, [previewOnEntry, didAutoOpenPreview, state.clips.length, isLoading]);

  // Load from scene IDs (entry from ShortsPlanPanel or saved-shorts list)
  useEffect(() => {
    if (!videoId || shortId) return;

    let cancelled = false;
    setIsLoading(true);
    setLoadError(null);

    (async () => {
      try {
        const res = await getAllVideoScenes(videoId, getAccessToken);
        if (cancelled) return;

        setMeta(res);
        setTitle(res.video_title ?? "");

        const requestedIds = new Set(sceneIdsParam.split(",").filter(Boolean));
        const scenes = requestedIds.size > 0
          ? res.scenes.filter((s) => requestedIds.has(s.scene_id))
          : res.scenes;

        const sourceType = res.source_type ?? "gdrive";
        // createClipFromScene returns clips with timelineStartMs=0; the
        // reducer normally lays them out via recomputeTimeline on
        // INIT_FROM_SCENES, but the original array we hold here stays
        // unmodified. Run the same layout locally so the per-clip
        // ``clip.timelineStartMs`` we feed into the subtitle generator
        // matches what the reducer applies — otherwise every scene's
        // subtitles stack at timeline 0 and never appear on later clips.
        const clips = recomputeTimeline(
          scenes.map((scene) => createClipFromScene(scene, videoId, sourceType)),
        );
        initFromScenes(videoId, sourceType, clips);

        // Auto-generate subtitles when entering with a curated scene set
        // (auto-shorts → "스크립트 편집" lands here with sceneIds=...).
        // Mirrors the manual onToggleScene path that fires
        // generateSubtitlesFromTranscript on each scene-add. The
        // generator returns [] for scenes without speaker_transcript,
        // so this is safe across the whole flow — operators always
        // see an editable subtitle list rather than an empty panel.
        //
        // 2026-05-22 (#22/#23 — operator request): host auto-STT
        // subtitles always go to ``state.subtitles`` regardless of V2
        // flag. The left SubtitleListNav + bottom SubtitleTrack read
        // from there. The ``텍스트 추가`` button continues to add to
        // ``state.overlays`` (separate channel), so the two stay
        // visually distinct — host subtitles on their own track at
        // the bottom of the timeline, operator-added text on
        // stackable tracks above. Q7's earlier branch routed both
        // into overlays when V2 was on, which left the left nav
        // empty and broke "재생 시 자막 바 따라 움직임" feedback.
        if (sceneIdsParam && scenes.length > 0) {
          for (let i = 0; i < scenes.length; i++) {
            // Prefer the speaker-tagged transcript when present (carries
            // diarisation + timestamps) and fall back to ``transcript_raw``
            // so older indexing runs without diarisation still produce
            // usable subtitle lines. The generator's synthetic-turn
            // fallback handles plain text either way.
            const speaker = scenes[i].speaker_transcript;
            const sourceText =
              speaker && speaker.trim().length > 0
                ? speaker
                : scenes[i].transcript_raw;
            const subs = generateSubtitlesFromTranscript(sourceText, clips[i]);
            for (const sub of subs) {
              editor.addSubtitle(sub);
            }
          }
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "장면을 불러올 수 없습니다.");
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [videoId, sceneIdsParam, shortId, getAccessToken, initFromScenes]);

  // Load from saved short ID (entry from SavedShortsPage)
  useEffect(() => {
    if (!shortId) return;

    let cancelled = false;
    setIsLoading(true);
    setLoadError(null);

    (async () => {
      try {
        const compRes = await getShortComposition(shortId, getAccessToken);
        if (cancelled) return;

        const comp = compRes.composition as {
          title?: string;
          scene_clips?: Array<{
            scene_id: string;
            video_id: string;
            source_type: string;
            start_ms: number;
            end_ms: number;
            timeline_start_ms: number;
            volume?: number;
          }>;
          subtitles?: Array<{
            text: string;
            start_ms: number;
            end_ms: number;
            style?: Record<string, unknown>;
          }>;
        };

        if (comp.title) setTitle(comp.title);

        const clips = (comp.scene_clips ?? []).map((sc, i) => ({
          id: `clip_loaded_${i}`,
          sceneId: sc.scene_id,
          videoId: sc.video_id,
          sourceType: sc.source_type,
          originalStartMs: sc.start_ms,
          originalEndMs: sc.end_ms,
          trimStartMs: sc.start_ms,
          trimEndMs: sc.end_ms,
          timelineStartMs: sc.timeline_start_ms,
          volume: sc.volume ?? 1.0,
        }));

        const firstClip = clips[0];
        initFromComposition({
          videoId: firstClip?.videoId ?? "",
          sourceType: firstClip?.sourceType ?? "gdrive",
          clips,
        });

        // Also fetch scenes so the scene list panel can display them
        if (firstClip?.videoId) {
          const scenesRes = await getAllVideoScenes(firstClip.videoId, getAccessToken);
          if (!cancelled) {
            setMeta(scenesRes);
            if (!comp.title) setTitle(scenesRes.video_title ?? "");

            // Subtitle hydration — two paths.
            //
            // 1) Composition already carries subtitles (Whisper refine
            //    has run, or the operator previously saved cues): load
            //    them verbatim via wire→editor converters so style
            //    fidelity (font, color, position, pill background,
            //    stroke, shadow) survives the round trip.
            //
            // 2) No saved subtitles: fall through to the legacy
            //    speaker_transcript auto-generation so the operator
            //    isn't dropped into an empty panel.
            //
            // 2026-05-19 — path (1) used to skip silently with a
            // "skip auto-gen, but don't load either" branch, so AI
            // shorts that DID have refined subtitles came up empty in
            // the editor.
            // Both saved- and auto-stt paths populate state.subtitles
            // (host channel). The earlier V2 branch routed them into
            // overlays, which broke #23 (left wrapper empty + selected
            // border not lighting up). Operator-added text overlays are
            // a separate channel and never come from this load path.
            const hasSavedSubtitles =
              (comp.subtitles?.length ?? 0) > 0;
            if (hasSavedSubtitles) {
              for (const wireSub of comp.subtitles ?? []) {
                editor.addSubtitle(wireSubtitleToEditorSubtitle(wireSub));
              }
            } else {
              for (let i = 0; i < clips.length; i++) {
                const sceneId = clips[i].sceneId;
                const scene = scenesRes.scenes.find(
                  (s) => s.scene_id === sceneId,
                );
                if (!scene) continue;
                const speaker = scene.speaker_transcript;
                const sourceText =
                  speaker && speaker.trim().length > 0
                    ? speaker
                    : scene.transcript_raw;
                if (!sourceText) continue;
                const subs = generateSubtitlesFromTranscript(
                  sourceText,
                  clips[i],
                );
                for (const sub of subs) {
                  editor.addSubtitle(sub);
                }
              }
            }
          }
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "구성을 불러올 수 없습니다.");
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [shortId, getAccessToken, initFromComposition]);

  // Keyboard shortcuts
  // Keyboard shortcuts — owned by useEditorKeyboard hook (L3). The
  // hook covers Space/Delete/Backspace/Escape plus the new J/K/L jog-
  // shuttle, Home/End boundary jumps, and reserves slots for I/O (L4)
  // and S (L5).
  useEditorKeyboard({
    state,
    setPlayhead,
    dispatchPlaybackEvent: editor.dispatchPlaybackEvent,
    selectClip: editor.selectClip,
    selectOverlay: editor.selectOverlay,
    selectSubtitle: editor.selectSubtitle,
    removeClip: editor.removeClip,
    removeOverlay: editor.removeOverlay,
    removeSubtitle: editor.removeSubtitle,
    setInPoint: editor.setInPoint,
    setOutPoint: editor.setOutPoint,
    splitAtPlayhead: editor.splitAtPlayhead,
    setRazorMode: editor.setRazorMode,
  });

  // Global razor-mode cursor — inject a <style> tag with !important so
  // the razor SVG cursor persists on ALL elements, overriding per-element
  // cursor rules (grab, pointer, col-resize, etc.). The previous
  // body.style.cursor approach was defeated by any child CSS that set its
  // own cursor property, causing the razor to revert on hover over
  // subtitle blocks, resize handles, and buttons.
  useEffect(() => {
    if (state.razorMode) {
      document.body.classList.add("razor-mode");
      const style = document.createElement("style");
      style.id = "razor-mode-cursor";
      style.textContent = `
        body.razor-mode, body.razor-mode * {
          cursor: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23234c77' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M8 19H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h3'/><path d='M16 5h3a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-3'/><line x1='12' x2='12' y1='4' y2='20'/></svg>") 10 10, crosshair !important;
        }
      `;
      document.head.appendChild(style);
      return () => {
        document.body.classList.remove("razor-mode");
        style.remove();
      };
    } else {
      document.body.classList.remove("razor-mode");
      const existing = document.getElementById("razor-mode-cursor");
      if (existing) existing.remove();
    }
  }, [state.razorMode]);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-grayscale-10">
        <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-heimdex-navy-500" />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-grayscale-10">
        <p className="text-sm text-red-h-500">{loadError}</p>
        <Link href="/export/shorts" className="text-sm text-heimdex-navy-500 hover:text-heimdex-navy-600">
          <span className="inline-flex items-center gap-1.5">
            <BackArrowIcon />
            쇼츠 목록으로 돌아가기
          </span>
        </Link>
      </div>
    );
  }


  return (
    <div
      className="font-pretendard h-full overflow-hidden bg-grayscale-10"
      // L9 / T9 — drag & drop import. Image files become a background
      // overlay at the playhead via the existing reducer factory; video
      // and audio fall back to a transient hint banner (their pipeline
      // requires backend upload — deferred to L10's editor-assets
      // endpoint).
      onDragOver={(e) => {
        // preventDefault is what flips the cursor to "copy" + stops
        // the browser from navigating to the dropped file.
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
        }
      }}
      onDrop={(e) => {
        if (!e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        const files = Array.from(e.dataTransfer.files);
        for (const file of files) {
          if (file.type.startsWith("image/")) {
            const reader = new FileReader();
            reader.onload = () => {
              const url = reader.result;
              if (typeof url === "string") {
                editor.addImageBackgroundOverlayAtPlayhead(url);
                setDropHint(`이미지 추가됨: ${file.name}`);
              }
            };
            reader.readAsDataURL(file);
          } else if (file.type.startsWith("video/")) {
            // TODO L10 — upload to /api/v1/editor/assets then add a
            // clip pointing at the returned URL. Until that endpoint
            // exists we just surface a hint so the operator knows the
            // drop wasn't ignored entirely.
            setDropHint(`비디오 업로드는 곧 지원됩니다: ${file.name}`);
          } else if (file.type.startsWith("audio/")) {
            setDropHint(`오디오 업로드는 곧 지원됩니다: ${file.name}`);
          } else {
            setDropHint(`지원하지 않는 형식: ${file.type || file.name}`);
          }
        }
      }}
    >
      {dropHint && (
        <div
          role="status"
          className="pointer-events-none fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full bg-grayscale-900 px-4 py-2 text-[12px] font-medium text-white shadow-card"
        >
          {dropHint}
        </div>
      )}
      <EditorLayout
        leftPanel={
          // figma: 1602:37844 (left subtitle panel) — wrapper hosts only the
          // subtitle nav (search + timeline-ordered list). Text/background
          // overlay editing lives in the right wrapper (figma 1602:40004).
          <div className="flex h-full min-h-0 flex-col">
            {/* figma: 1670:186255 (자막 좌측 패널) — timeline-ordered subtitle nav.
                좌측 wrapper 는 검색 + 자막 리스트만 노출한다. 타임라인의 클립을
                선택해도 여기서 클립 속성을 띄우지 않는다 — 자막 외 편집 UI 는
                전부 우측 wrapper (figma 1602:40004) 로 격리되어야 한다. */}
            {/* figma: 1670:186095 — row click seeks playhead to subtitle.startMs */}
            <SubtitleListNav
              subtitles={timelineSubtitles}
              selectedSubtitleIndex={timelineSelectedSubtitleIndex}
              onSelectSubtitle={handleTimelineSelectSubtitle}
              onSeek={setPlayhead}
              onUpdateSubtitleText={(index, text) =>
                editor.updateSubtitle(index, { text })
              }
            />
          </div>
        }
        preview={
          // 2026-05-25 — Unmount the inline PreviewPanel while the
          // FullscreenOverlay is open. Both surfaces share a
          // ``usePlaybackSync`` instance pointed at the same playback
          // URL; mounting them simultaneously means two <video>
          // elements race for the same signed/CDN source, and the
          // fullscreen modal's video can stay on a black first-frame
          // until the inline one finishes its own ``video.load()``.
          // Hiding the inline panel entirely guarantees the modal owns
          // the source. When the operator closes fullscreen the panel
          // re-mounts and reloads from the current playhead.
          isFullscreen ? null : (
            <PreviewPanel
              clips={state.clips}
              subtitles={state.subtitles}
              overlays={state.overlays}
              selectedOverlayId={state.selectedOverlayId}
              onSelectOverlay={editor.selectOverlay}
              onUpdateOverlay={editor.updateOverlay}
              onRemoveOverlay={editor.removeOverlay}
              onRemoveSubtitle={editor.removeSubtitle}
              playheadMs={state.playheadMs}
              playback={state.playback}
              totalDurationMs={state.totalDurationMs}
              selectedSubtitleIndex={state.selectedSubtitleIndex}
              onPlayheadChange={setPlayhead}
              dispatchPlaybackEvent={editor.dispatchPlaybackEvent}
              onSelectSubtitle={selectSubtitle}
              onUpdateSubtitlePosition={handleSubtitlePositionChange}
              onUpdateSubtitleFontSize={handleSubtitleFontSizeChange}
              videoTransform={state.videoTransform}
              onUpdateVideoPosition={editor.updateVideoPosition}
              onUpdateVideoScale={editor.updateVideoScale}
              onUpdateVideoRotation={editor.updateVideoRotation}
              layerOrder={state.layerOrder}
              letterbox={state.letterbox}
              onUpdateLetterbox={editor.setLetterbox}
              onPushHistory={editor.pushHistory}
              selectedVideo={state.selectedVideo}
              selectedLetterbox={state.selectedLetterbox}
              onSelectVideo={editor.selectVideo}
              onSelectLetterbox={editor.selectLetterbox}
              onClearSelections={editor.clearAllSelections}
            />
          )
        }
        rightPanel={
          // figma: 1607:65302 right column (텍스트/배경/템플릿 3탭)
          // 배경 탭 = figma 1602:41198 BackgroundPanel.
          // 템플릿 탭 = figma 1602:41198 TemplatePanel (presetsApi 와이어).
          (() => {
            const backgroundTab = (
              <BackgroundPanel
                state={state}
                onAddSolidBackground={editor.addBackgroundOverlayAtPlayhead}
                onAddImageBackground={editor.addImageBackgroundOverlayAtPlayhead}
                onUpdateOverlay={editor.updateOverlay}
                onReorderOverlay={editor.reorderOverlay}
                onReorderLayer={editor.reorderLayer}
                onSetLetterbox={(next) => {
                  // Snapshot the current letterbox so Ctrl+Z restores
                  // the prior state — covers both add/remove and color
                  // changes through the popover.
                  editor.pushHistory({
                    kind: "letterbox",
                    letterbox: state.letterbox,
                  });
                  editor.setLetterbox(next);
                }}
                onUpdateVideoPosition={(x, y) => {
                  // Snapshot the pre-align position so Ctrl+Z reverts
                  // the snap in one stroke — mirrors the letterbox
                  // wrapper above.
                  editor.pushHistory({
                    kind: "video_position",
                    x: state.videoTransform.x,
                    y: state.videoTransform.y,
                  });
                  editor.updateVideoPosition(x, y);
                }}
                onSetVideoOutline={editor.setVideoOutline}
                onSetVideoShadow={editor.setVideoShadow}
              />
            );
            const templateTab = (
              <TemplatePanel
                presets={presetsApi.presets}
                starterTemplates={STARTER_TEMPLATES}
                onApplyStarter={(template) => {
                  // Dual behavior:
                  //   * Text overlay selected → apply the template's
                  //     visual layer (font, color, transform, effects)
                  //     to it, preserving the existing text + identity
                  //     + timing. Operator stays anchored on the same
                  //     subtitle slot but gets a fresh look.
                  //   * Nothing selected (or a background overlay
                  //     selected) → drop a brand new text overlay at
                  //     the playhead with the template's full payload,
                  //     including its example text.
                  if (selectedOverlay?.kind === "text") {
                    const { text: _templateText, ...visualStyle } =
                      template.style;
                    editor.updateOverlay(selectedOverlay.id, {
                      ...selectedOverlay,
                      ...visualStyle,
                    });
                  } else {
                    editor.addStarterTextOverlay(template.style);
                  }
                }}
                isLoading={presetsApi.isLoading}
                error={presetsApi.error}
                selectedId={selectedTemplateId}
                onSelect={setSelectedTemplateId}
                onApply={(preset) => {
                  // Composition preset → atomic apply at the current
                  // playhead (single Ctrl+Z reverts the whole apply,
                  // per applyCompositionTemplate's snapshot wrap).
                  // text / background presets → legacy per-overlay
                  // merge that requires a selected overlay of the
                  // matching kind.
                  if (preset.kind === "composition") {
                    const payload = presetsApi.parseComposition(preset);
                    if (!payload) return;
                    editor.applyCompositionTemplate(payload);
                    return;
                  }
                  if (!selectedOverlay) return;
                  if (selectedOverlay.kind !== preset.kind) return;
                  const merged = presetsApi.applyTo(selectedOverlay, preset);
                  editor.updateOverlay(selectedOverlay.id, merged);
                }}
                onOpenSaveDialog={() => setTemplateDialogOpen(true)}
                onDelete={(preset) => void presetsApi.remove(preset.id)}
              />
            );
            return (
              <RightPanel
                backgroundTab={backgroundTab}
                templateTab={templateTab}
              >
                <OverlayPanel
                  state={state}
                  onAddTextOverlay={editor.addTextOverlayAtPlayhead}
                  onAddBackgroundOverlay={editor.addBackgroundOverlayAtPlayhead}
                  onAddImageBackgroundOverlay={editor.addImageBackgroundOverlayAtPlayhead}
                  onUpdateOverlay={editor.updateOverlay}
                  onRemoveOverlay={editor.removeOverlay}
                  onSelectOverlay={editor.selectOverlay}
                  onReorderOverlay={editor.reorderOverlay}
                  onUpdateAllSubtitleStyles={editor.updateAllSubtitleStyles}
                />
              </RightPanel>
            );
          })()
        }
        timeline={
          <TimelinePanel
            clips={state.clips}
            subtitles={timelineSubtitles}
            textOverlaysForTimeline={timelineTextOverlays}
            selectedTextOverlayId={state.selectedOverlayId}
            onSelectTextOverlay={editor.selectOverlay}
            onUpdateTextOverlay={(id, updates) =>
              editor.updateOverlay(id, updates)
            }
            onReorderTextOverlay={(id, direction, count) => {
              // Cross-track row swap (L2). Multi-row drags dispatch the
              // reorder action N times — the reducer is fast and each
              // dispatch already snapshots history, so undo gives the
              // operator granular per-row reversibility. Future
              // refinement: introduce a REORDER_OVERLAY_BY action that
              // moves N slots in one dispatch (one snapshot).
              for (let i = 0; i < count; i++) {
                editor.reorderOverlay(id, direction);
              }
            }}
            zoom={state.zoom}
            playheadMs={state.playheadMs}
            playback={state.playback}
            totalDurationMs={state.totalDurationMs}
            selectedClipIndex={state.selectedClipIndex}
            selectedSubtitleIndex={timelineSelectedSubtitleIndex}
            onSelectClip={editor.selectClip}
            onSelectSubtitle={handleTimelineSelectSubtitle}
            onTrimClip={editor.trimClip}
            onMoveClip={editor.moveClip}
            onReorderClips={editor.reorderClips}
            onUpdateSubtitle={handleTimelineUpdateSubtitle}
            onAddSubtitle={handleTimelineAddSubtitle}
            onRemoveClip={editor.removeClip}
            onRemoveSubtitle={handleTimelineRemoveSubtitle}
            onTogglePlay={() => editor.dispatchPlaybackEvent({ kind: "TOGGLE" })}
            onSeek={setPlayhead}
            onZoomChange={editor.setZoom}
            playbackRate={state.playback.kind === "playing" ? state.playback.rate : (state.playback.kind === "paused" ? state.playback.resumeRate : 1)}
            onPlaybackRateChange={(rate) => editor.dispatchPlaybackEvent({ kind: "SET_RATE", rate })}
            volume={masterVolume}
            onVolumeChange={setMasterVolume}
            onToggleFullscreen={() => setIsFullscreen(true)}
            onPushHistory={editor.pushHistory}
            onSplitAtPlayhead={editor.splitAtPlayhead}
            onActivateRazor={() => editor.setRazorMode(!state.razorMode)}
            razorMode={state.razorMode}
            onRazorSplitClip={(index, atMs) => {
              editor.splitClip(index, atMs);
              editor.setRazorMode(false);
            }}
            onRazorSplitSubtitle={(index, atMs) => {
              editor.splitSubtitle(index, atMs);
              editor.setRazorMode(false);
            }}
          />
        }
      />

      {isFullscreen && (
        <FullscreenOverlay
          clips={state.clips}
          subtitles={state.subtitles}
          overlays={state.overlays}
          selectedOverlayId={state.selectedOverlayId}
          onSelectOverlay={editor.selectOverlay}
          onUpdateOverlay={editor.updateOverlay}
          onRemoveOverlay={editor.removeOverlay}
          onRemoveSubtitle={editor.removeSubtitle}
          playheadMs={state.playheadMs}
          playback={state.playback}
          totalDurationMs={state.totalDurationMs}
          selectedSubtitleIndex={state.selectedSubtitleIndex}
          onPlayheadChange={setPlayhead}
          dispatchPlaybackEvent={editor.dispatchPlaybackEvent}
          onSelectSubtitle={selectSubtitle}
          onUpdateSubtitlePosition={handleSubtitlePositionChange}
          onUpdateSubtitleFontSize={handleSubtitleFontSizeChange}
          onClose={() => setIsFullscreen(false)}
          filename={title || meta?.video_title || undefined}
          letterbox={state.letterbox}
          layerOrder={state.layerOrder}
          videoTransform={state.videoTransform}
        />
      )}

      <TemplateSaveDialog
        open={templateDialogOpen}
        onClose={() => setTemplateDialogOpen(false)}
        onSave={handleTemplateSave}
        mode="composition"
      />
    </div>
  );
}
