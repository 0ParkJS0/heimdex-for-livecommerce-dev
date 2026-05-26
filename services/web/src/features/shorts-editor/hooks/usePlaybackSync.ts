import { useRef, useEffect, useCallback } from "react";
import { getAgentPlaybackUrl, getCloudPlaybackUrl } from "@/lib/agent";
import type { EditorClip, Playback, PlaybackEvent } from "../lib/types";
import { getSourceTime } from "../lib/source-time";
import { getClipDuration } from "../lib/timeline-math";

interface PlaybackSyncOptions {
  clips: EditorClip[];
  playheadMs: number;
  playback: Playback;
  onPlayheadChange: (ms: number) => void;
  dispatchPlaybackEvent: (event: PlaybackEvent) => void;
}

function getVideoUrl(videoId: string, sourceType: string): string {
  if (sourceType === "gdrive") {
    return getCloudPlaybackUrl(videoId);
  }
  return getAgentPlaybackUrl(videoId);
}

function isPlaybackActive(pb: Playback): boolean {
  return pb.kind === "playing";
}

function getPlaybackRate(pb: Playback): number {
  if (pb.kind === "playing") return pb.rate;
  return 1;
}

/**
 * Syncs a <video> element with editor playback state machine.
 * Handles multi-clip playback by switching video sources.
 */
export function usePlaybackSync({
  clips,
  playheadMs,
  playback,
  onPlayheadChange,
  dispatchPlaybackEvent,
}: PlaybackSyncOptions) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const preloadRef = useRef<HTMLVideoElement>(null);
  const animFrameRef = useRef<number>(0);
  const lastSourceRef = useRef<{ videoId: string; url: string } | null>(null);
  const lastClipIndexRef = useRef<number>(-1);
  const seekingRef = useRef(false);
  const playheadAtStartRef = useRef(0);
  const startTimeRef = useRef(0);

  const playheadMsRef = useRef(playheadMs);
  playheadMsRef.current = playheadMs;

  const playing = isPlaybackActive(playback);
  const rate = getPlaybackRate(playback);

  const currentSource = getSourceTime(clips, playheadMs);
  const currentClipIndex = currentSource?.clipIndex ?? -1;

  // Load video source when clip changes (source switch only)
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !currentSource) return;

    const url = getVideoUrl(currentSource.videoId, currentSource.sourceType);

    if (lastSourceRef.current?.url !== url) {
      lastSourceRef.current = { videoId: currentSource.videoId, url };
      video.src = url;
      video.load();
    }

    if (currentClipIndex !== lastClipIndexRef.current) {
      lastClipIndexRef.current = currentClipIndex;
      const targetTime = currentSource.sourceMs / 1000;
      seekingRef.current = true;
      video.currentTime = targetTime;
    }
  }, [currentClipIndex, currentSource?.videoId, currentSource?.sourceType]);

  // Apply playbackRate whenever it changes or after a source reload.
  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.playbackRate = rate;
    }
  }, [rate, currentClipIndex]);

  // Seek video when playhead changes while NOT playing (user scrubbing)
  useEffect(() => {
    if (playing || !currentSource || !videoRef.current) return;

    const targetTime = currentSource.sourceMs / 1000;
    if (Math.abs(videoRef.current.currentTime - targetTime) > 0.3) {
      videoRef.current.currentTime = targetTime;
    }
  }, [playing, playheadMs, currentSource?.sourceMs]);

  // Preload next clip's video when playing
  useEffect(() => {
    if (!playing || !currentSource || !preloadRef.current) return;

    const nextClipIndex = currentSource.clipIndex + 1;
    if (nextClipIndex >= clips.length) return;

    const nextClip = clips[nextClipIndex];
    const nextUrl = getVideoUrl(nextClip.videoId, nextClip.sourceType);

    if (preloadRef.current.src !== nextUrl) {
      preloadRef.current.src = nextUrl;
      preloadRef.current.preload = "auto";
    }
  }, [playing, currentClipIndex, clips]);

  // Play/pause sync
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    // Always honour the pause request, even when the playhead is
    // sitting at totalDuration (where getSourceTime returns null
    // because the strict ``timelineMs < clipEnd`` check excludes
    // the end frame). Skipping the pause there left the underlying
    // <video> element playing past the last clip's trim window into
    // the source video's untrimmed frames.
    if (!playing) {
      video.pause();
      cancelAnimationFrame(animFrameRef.current);
      return;
    }

    const source = getSourceTime(clips, playheadMsRef.current);
    if (!source) return;

    playheadAtStartRef.current = playheadMsRef.current;
    startTimeRef.current = performance.now();

    const url = getVideoUrl(source.videoId, source.sourceType);
    if (lastSourceRef.current?.url !== url) {
      lastSourceRef.current = { videoId: source.videoId, url };
      video.src = url;
      video.load();
    }

    const targetTime = source.sourceMs / 1000;
    if (Math.abs(video.currentTime - targetTime) > 0.3) {
      video.currentTime = targetTime;
    }
    video.play().catch(() => {
      dispatchPlaybackEvent({ kind: "HARD_PAUSE" });
    });
  }, [playing, clips, dispatchPlaybackEvent]);

  // Animation frame loop for smooth playhead updates during playback
  useEffect(() => {
    if (!playing) return;

    const tick = () => {
      const elapsed = performance.now() - startTimeRef.current;
      const newPlayhead = Math.round(
        playheadAtStartRef.current + elapsed * rate,
      );

      const totalEnd = clips.length > 0
        ? clips[clips.length - 1].timelineStartMs + getClipDuration(clips[clips.length - 1])
        : 0;

      if (newPlayhead >= totalEnd) {
        // Loop back to the start of the timeline instead of pausing
        // at the end. Resets the playhead, the rAF time anchor, and
        // the underlying <video> element to the first clip's trim
        // start so playback continues seamlessly from 0ms. If there
        // are no clips (defensive — totalEnd would also be 0) we
        // fall through to REACHED_END so the reducer can settle.
        const firstClip = clips[0];
        if (firstClip) {
          playheadAtStartRef.current = 0;
          startTimeRef.current = performance.now();
          onPlayheadChange(0);
          if (videoRef.current) {
            const url = getVideoUrl(firstClip.videoId, firstClip.sourceType);
            if (lastSourceRef.current?.url !== url) {
              lastSourceRef.current = { videoId: firstClip.videoId, url };
              videoRef.current.src = url;
              videoRef.current.load();
            }
            videoRef.current.currentTime = firstClip.trimStartMs / 1000;
          }
          lastClipIndexRef.current = 0;
          animFrameRef.current = requestAnimationFrame(tick);
          return;
        }
        dispatchPlaybackEvent({ kind: "REACHED_END" });
        onPlayheadChange(totalEnd);
        return;
      }

      const newSource = getSourceTime(clips, newPlayhead);
      if (newSource && newSource.clipIndex !== lastClipIndexRef.current) {
        onPlayheadChange(newPlayhead);
        playheadAtStartRef.current = newPlayhead;
        startTimeRef.current = performance.now();
      } else {
        onPlayheadChange(newPlayhead);
      }

      animFrameRef.current = requestAnimationFrame(tick);
    };

    animFrameRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [playing, rate, clips, onPlayheadChange, dispatchPlaybackEvent]);

  const onSeeked = useCallback(() => {
    seekingRef.current = false;
    dispatchPlaybackEvent({ kind: "SEEK_DONE" });
  }, [dispatchPlaybackEvent]);

  const onEnded = useCallback(() => {
    if (!currentSource) return;
    const nextClipIndex = currentSource.clipIndex + 1;
    if (nextClipIndex < clips.length) {
      const nextClip = clips[nextClipIndex];
      onPlayheadChange(nextClip.timelineStartMs);
    } else {
      dispatchPlaybackEvent({ kind: "REACHED_END" });
    }
  }, [currentSource, clips, onPlayheadChange, dispatchPlaybackEvent]);

  const seekTo = useCallback(
    (ms: number) => {
      onPlayheadChange(ms);
      dispatchPlaybackEvent({ kind: "SEEK", toMs: ms });
      const source = getSourceTime(clips, ms);
      if (source && videoRef.current) {
        const url = getVideoUrl(source.videoId, source.sourceType);
        if (lastSourceRef.current?.url !== url) {
          lastSourceRef.current = { videoId: source.videoId, url };
          videoRef.current.src = url;
          videoRef.current.load();
        }
        videoRef.current.currentTime = source.sourceMs / 1000;
      }
    },
    [clips, onPlayheadChange, dispatchPlaybackEvent],
  );

  const togglePlay = useCallback(() => {
    dispatchPlaybackEvent({ kind: "TOGGLE" });
  }, [dispatchPlaybackEvent]);

  return {
    videoRef,
    preloadRef,
    currentSource,
    seekTo,
    togglePlay,
    onSeeked,
    onEnded,
  };
}
