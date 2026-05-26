"use client";

import { useEffect, useState } from "react";

import { getAllVideoScenes } from "@/lib/api/videos";
import type { VideoScenesResponse } from "@/lib/types";

type TokenGetter = () => Promise<string | null>;

interface State {
  meta: VideoScenesResponse | null;
  isLoading: boolean;
  error: Error | null;
}

/**
 * Load a video's scene metadata + the full scene list. The script panel
 * in the inspector wants per-scene transcripts as a fallback path when
 * ``ClipMemberResponse.transcript`` is undefined for an older backend,
 * and the full list lets us render speaker turns without a second
 * fetch per clip. Loads all pages explicitly so long livecommerce videos
 * are not capped at the API's per-request page limit.
 */
export function useVideoMeta(videoId: string, getToken: TokenGetter): State {
  const [state, setState] = useState<State>({
    meta: null,
    isLoading: Boolean(videoId),
    error: null,
  });

  useEffect(() => {
    if (!videoId) {
      setState({ meta: null, isLoading: false, error: null });
      return;
    }

    let cancelled = false;
    setState({ meta: null, isLoading: true, error: null });

    getAllVideoScenes(videoId, getToken)
      .then((res) => {
        if (cancelled) return;
        setState({ meta: res, isLoading: false, error: null });
      })
      .catch((err) => {
        if (cancelled) return;
        const error = err instanceof Error ? err : new Error(String(err));
        setState({ meta: null, isLoading: false, error });
      });

    return () => {
      cancelled = true;
    };
  }, [videoId, getToken]);

  return state;
}
