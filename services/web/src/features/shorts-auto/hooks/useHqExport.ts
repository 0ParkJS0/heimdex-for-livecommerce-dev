"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  getAgentHqRenderOutputUrl,
  getAgentHqRenderStatus,
  startAgentHqRender,
} from "@/lib/agent";
import {
  getDriveSourceFacts,
  HqExportNotEnabledError,
} from "@/lib/api/hq-export";
import { getShortComposition } from "@/lib/api/shorts-render";

type TokenGetter = () => Promise<string | null>;

export type HqExportState =
  | { kind: "idle" }
  | { kind: "preparing" } // fetching composition + source facts, dispatching
  | { kind: "rendering"; agentJobId: string }
  | { kind: "done"; agentJobId: string; outputUrl: string }
  | { kind: "failed"; error: string };

const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 900; // ~30 min ceiling at 2s

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/** Unique source video_ids from a CompositionSpec's scene_clips. */
export function extractVideoIds(composition: Record<string, unknown>): string[] {
  const clips =
    (composition?.scene_clips as Array<{ video_id?: string }> | undefined) ?? [];
  const ids = new Set<string>();
  for (const c of clips) {
    if (c?.video_id) ids.add(c.video_id);
  }
  return Array.from(ids);
}

/**
 * Orchestrates high-quality (source-resolution) export for a completed render
 * job, keyed by the render job id:
 *   1. GET /api/shorts/{jobId}/composition  (the approved CompositionSpec)
 *   2. extract video_ids → GET /api/drive/source-facts (per-video Drive facts)
 *   3. POST http://127.0.0.1:8787/hq-render (the local agent renders)
 *   4. poll the agent until done → expose the localhost output URL
 *
 * The web never sees the originals or the mount — it only forwards the
 * server-provided facts to the agent. Caller gates entry on agent availability.
 */
export function useHqExport(getToken: TokenGetter) {
  const [states, setStates] = useState<Record<string, HqExportState>>({});
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const setOne = useCallback((jobId: string, s: HqExportState) => {
    if (!mountedRef.current) return;
    setStates((prev) => ({ ...prev, [jobId]: s }));
  }, []);

  const getState = useCallback(
    (jobId: string): HqExportState => states[jobId] ?? { kind: "idle" },
    [states],
  );

  const start = useCallback(
    async (renderJobId: string) => {
      setOne(renderJobId, { kind: "preparing" });
      try {
        const compRes = await getShortComposition(renderJobId, getToken);
        const composition = compRes.composition;
        const videoIds = extractVideoIds(composition);
        if (videoIds.length === 0) {
          throw new Error("이 숏폼에 원본 영상 정보가 없습니다.");
        }

        const facts = await getDriveSourceFacts(videoIds, getToken);
        if (facts.missing.length > 0) {
          throw new Error(
            `${facts.missing.length}개 영상의 원본을 찾을 수 없습니다.`,
          );
        }

        const job = await startAgentHqRender({
          spec: composition,
          sources: facts.items,
        });
        if (!mountedRef.current) return;

        if (job.status === "failed") {
          setOne(renderJobId, { kind: "failed", error: job.error ?? "렌더링 실패" });
          return;
        }
        if (job.status === "done") {
          setOne(renderJobId, {
            kind: "done",
            agentJobId: job.job_id,
            outputUrl: getAgentHqRenderOutputUrl(job.job_id),
          });
          return;
        }

        setOne(renderJobId, { kind: "rendering", agentJobId: job.job_id });
        for (let i = 0; i < MAX_POLLS; i++) {
          await sleep(POLL_INTERVAL_MS);
          if (!mountedRef.current) return;
          const s = await getAgentHqRenderStatus(job.job_id);
          if (!s) continue; // transient unreachable → retry next tick
          if (s.status === "done") {
            setOne(renderJobId, {
              kind: "done",
              agentJobId: s.job_id,
              outputUrl: getAgentHqRenderOutputUrl(s.job_id),
            });
            return;
          }
          if (s.status === "failed") {
            setOne(renderJobId, {
              kind: "failed",
              error: s.error ?? "렌더링 실패",
            });
            return;
          }
        }
        setOne(renderJobId, { kind: "failed", error: "렌더링 시간이 초과되었습니다." });
      } catch (err) {
        const message =
          err instanceof HqExportNotEnabledError
            ? err.message
            : err instanceof Error
              ? err.message
              : String(err);
        setOne(renderJobId, { kind: "failed", error: message });
      }
    },
    [getToken, setOne],
  );

  return { getState, start };
}
