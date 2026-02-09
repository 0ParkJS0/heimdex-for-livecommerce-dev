import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SearchResults } from "@/features/search/components/SearchResults";
import type {
  SearchResponse,
  SceneSearchResponse,
  SegmentResult,
  SceneResult,
  DebugInfo,
} from "@/lib/api";

const baseDebug: DebugInfo = {
  lexical_rank: 1,
  lexical_score: 1,
  vector_rank: 1,
  vector_score: 1,
  lexical_contribution: 0.5,
  vector_contribution: 0.5,
  fused_score: 1,
  quality_factor: 1,
  adjusted_score: 1,
  diversification_penalty: false,
};

const segmentResult: SegmentResult = {
  segment_id: "seg-1",
  video_id: "video-1",
  library_id: "lib-1",
  library_name: "Main Library",
  start_ms: 1000,
  end_ms: 4000,
  snippet: "Segment snippet text",
  thumbnail_url: null,
  source_type: "gdrive",
  required_drive_nickname: null,
  capture_time: null,
  people_cluster_ids: [],
  debug: baseDebug,
};

const segmentResponse: SearchResponse = {
  results: [segmentResult],
  total_candidates: 1,
  facets: { libraries: [], source_types: [], people_cluster_ids: [] },
  query: "test",
  alpha: 0.5,
};

const sceneResult: SceneResult = {
  scene_id: "vid1_scene_0",
  video_id: "video-1",
  library_id: "lib-1",
  library_name: "Scene Library",
  start_ms: 0,
  end_ms: 5000,
  snippet: "Scene transcript text",
  thumbnail_url: null,
  source_type: "gdrive",
  required_drive_nickname: null,
  capture_time: null,
  people_cluster_ids: [],
  speech_segment_count: 3,
  debug: baseDebug,
};

const sceneResponse: SceneSearchResponse = {
  results: [sceneResult],
  total_candidates: 1,
  facets: { libraries: [], source_types: [], people_cluster_ids: [] },
  query: "test",
  alpha: 0.5,
  result_type: "scene",
};

const emptyResponse: SearchResponse = {
  results: [],
  total_candidates: 0,
  facets: { libraries: [], source_types: [], people_cluster_ids: [] },
  query: "test",
  alpha: 0.5,
};

describe("SearchResults with segment response", () => {
  it("renders segment snippet and library name", () => {
    render(
      <SearchResults response={segmentResponse} showDebug={false} agentAvailable={false} />
    );

    expect(screen.getByText("Segment snippet text")).toBeInTheDocument();
    expect(screen.getByText("Main Library")).toBeInTheDocument();
  });

  it("renders disabled playback button for segments", () => {
    render(
      <SearchResults response={segmentResponse} showDebug={false} agentAvailable={false} />
    );

    const playButton = screen.getByRole("button", { name: /play \(not available\)/i });
    expect(playButton).toBeDisabled();
  });

  it("renders empty state message when no results", () => {
    render(
      <SearchResults response={emptyResponse} showDebug={false} agentAvailable={false} />
    );

    expect(
      screen.getByText("No results found. Try a different search query.")
    ).toBeInTheDocument();
  });
});

describe("SearchResults with scene response", () => {
  it("renders scene snippet and library name", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />
    );

    expect(screen.getByText("Scene transcript text")).toBeInTheDocument();
    expect(screen.getByText("Scene Library")).toBeInTheDocument();
  });

  it("renders speech segment count badge", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />
    );

    expect(screen.getByText("3 segments")).toBeInTheDocument();
  });

  it("renders scene results badge", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />
    );

    expect(screen.getByText("Scene results")).toBeInTheDocument();
  });

  it("renders enabled play button when agent is available", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={true} />
    );

    const playButton = screen.getByRole("button", { name: /play/i });
    expect(playButton).not.toBeDisabled();
  });

  it("renders disabled play button when agent is offline", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />
    );

    const playButton = screen.getByRole("button", { name: /play \(agent offline\)/i });
    expect(playButton).toBeDisabled();
  });
});
