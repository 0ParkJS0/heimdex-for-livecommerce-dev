import type { EditorState, CompositionSpec } from "./types";
import { DEFAULT_OUTPUT } from "../constants";

/**
 * Build a CompositionSpec dict from the editor state.
 * Mirrors the highlight_reel service's build_composition_dict() pattern.
 */
export function buildCompositionSpec(
  state: EditorState,
  title?: string | null,
): CompositionSpec {
  return {
    output: { ...DEFAULT_OUTPUT },
    scene_clips: state.clips.map((clip) => ({
      scene_id: clip.sceneId,
      video_id: clip.videoId,
      source_type: clip.sourceType,
      start_ms: clip.trimStartMs,
      end_ms: clip.trimEndMs,
      timeline_start_ms: clip.timelineStartMs,
      volume: clip.volume,
      crop_x: 0.0,
      crop_y: 0.0,
      crop_w: 1.0,
      crop_h: 1.0,
    })),
    subtitles: state.subtitles.map((sub) => ({
      text: sub.text,
      start_ms: sub.startMs,
      end_ms: sub.endMs,
      style: {
        font_family: sub.style.fontFamily,
        font_size_px: sub.style.fontSizePx,
        font_color: sub.style.fontColor,
        font_weight: sub.style.fontWeight,
        position_x: sub.style.positionX,
        position_y: sub.style.positionY,
        background_color: sub.style.backgroundColor,
        background_opacity: sub.style.backgroundOpacity,
      },
    })),
    transitions: [],
    title: title ?? null,
    version: 1,
  };
}
