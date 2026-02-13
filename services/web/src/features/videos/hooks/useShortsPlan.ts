"use client";

import { useState, useCallback } from "react";
import { useAuth } from "@/lib/auth";
import { generateShortsPlan } from "@/lib/api/shorts";
import { exportToPremiere } from "@/lib/agent-export";
import type {
  ExportPremiereResponse,
  ShortsCandidateResponse,
  ShortsPlanRequest,
} from "@/lib/types";
import { ApiError } from "@/lib/types";

export interface UseShortsPlanReturn {
  candidates: ShortsCandidateResponse[];
  isGenerating: boolean;
  planError: string | null;
  totalScenes: number;
  eligibleScenes: number;
  selectedIds: Set<string>;
  isExporting: boolean;
  exportError: string | null;
  exportResult: ExportPremiereResponse | null;
  generatePlan: (videoId: string, request?: ShortsPlanRequest) => Promise<void>;
  toggleCandidate: (candidateId: string) => void;
  selectAll: () => void;
  deselectAll: () => void;
  exportSelectedToPremiere: (config: {
    projectName: string;
    outputDir: string;
    frameRate: number;
  }) => Promise<void>;
  clearExportResult: () => void;
  reset: () => void;
}

export function useShortsPlan(): UseShortsPlanReturn {
  const { getAccessToken } = useAuth();

  const [candidates, setCandidates] = useState<ShortsCandidateResponse[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [totalScenes, setTotalScenes] = useState(0);
  const [eligibleScenes, setEligibleScenes] = useState(0);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<ExportPremiereResponse | null>(null);

  const generatePlan = useCallback(
    async (videoId: string, request?: ShortsPlanRequest) => {
      setIsGenerating(true);
      setPlanError(null);
      setExportError(null);
      setExportResult(null);

      try {
        const response = await generateShortsPlan(videoId, request, getAccessToken);
        setCandidates(response.candidates);
        setTotalScenes(response.total_scenes);
        setEligibleScenes(response.eligible_scenes);
        setSelectedIds(new Set(response.candidates.map((candidate) => candidate.candidate_id)));
      } catch (err) {
        const message = err instanceof ApiError ? err.detail : "Failed to generate shorts plan";
        setPlanError(message);
        setCandidates([]);
        setSelectedIds(new Set());
        setTotalScenes(0);
        setEligibleScenes(0);
      } finally {
        setIsGenerating(false);
      }
    },
    [getAccessToken],
  );

  const toggleCandidate = useCallback((candidateId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(candidateId)) {
        next.delete(candidateId);
      } else {
        next.add(candidateId);
      }
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(candidates.map((candidate) => candidate.candidate_id)));
  }, [candidates]);

  const deselectAll = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const exportSelectedToPremiere = useCallback(
    async (config: { projectName: string; outputDir: string; frameRate: number }) => {
      const selectedCandidates = candidates.filter((candidate) =>
        selectedIds.has(candidate.candidate_id),
      );
      if (selectedCandidates.length === 0) {
        setExportError("Select at least one candidate to export");
        return;
      }

      setIsExporting(true);
      setExportError(null);
      setExportResult(null);

      try {
        const clips = selectedCandidates.map((candidate, index) => ({
          video_id: candidate.video_id,
          scene_id: candidate.scene_ids[0] || candidate.candidate_id,
          clip_name: candidate.title_suggestion || `Clip ${index + 1}`,
          start_ms: candidate.start_ms,
          end_ms: candidate.end_ms,
        }));

        const result = await exportToPremiere({
          project_name: config.projectName,
          format: "edl",
          frame_rate: config.frameRate,
          output_dir: config.outputDir,
          clips,
        });

        setExportResult(result);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to export to Premiere";
        setExportError(message);
      } finally {
        setIsExporting(false);
      }
    },
    [candidates, selectedIds],
  );

  const clearExportResult = useCallback(() => {
    setExportResult(null);
    setExportError(null);
  }, []);

  const reset = useCallback(() => {
    setCandidates([]);
    setIsGenerating(false);
    setPlanError(null);
    setTotalScenes(0);
    setEligibleScenes(0);
    setSelectedIds(new Set());
    setIsExporting(false);
    setExportError(null);
    setExportResult(null);
  }, []);

  return {
    candidates,
    isGenerating,
    planError,
    totalScenes,
    eligibleScenes,
    selectedIds,
    isExporting,
    exportError,
    exportResult,
    generatePlan,
    toggleCandidate,
    selectAll,
    deselectAll,
    exportSelectedToPremiere,
    clearExportResult,
    reset,
  };
}
