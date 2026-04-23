/**
 * UI behavior: scorer chip only shows when the response says the LLM
 * produced the clips. Kept narrowly focused so the test doesn't break
 * on every clip-card layout tweak.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AutoSelectPreview } from "../components/AutoSelectPreview";
import type { AutoSelectResponse } from "@/lib/types";

// AutoClipCard pulls in next/link + playback URL helpers we don't care
// about in this unit — stub it so the preview renders independently.
vi.mock("../components/AutoClipCard", () => ({
  AutoClipCard: ({ clip }: { clip: { scene_ids: string[] } }) => (
    <div data-testid="clip-card">{clip.scene_ids.join(",")}</div>
  ),
}));

function makeSelection(scorer: "pure" | "llm" | undefined): AutoSelectResponse {
  return {
    video_id: "vid",
    mode: "both",
    clips: [
      {
        scene_ids: ["vid_scene_000"],
        members: [{ scene_id: "vid_scene_000", start_ms: 0, end_ms: 5000, score: 0.9 }],
        start_ms: 0,
        end_ms: 5000,
        duration_ms: 5000,
        score: 0.9,
        reasons: [],
        is_continuous: true,
      },
    ],
    total_duration_ms: 5000,
    skipped_reason: null,
    scorer,
  };
}

describe("AutoSelectPreview scorer chip", () => {
  it("shows AI selection chip when scorer=llm", () => {
    render(
      <AutoSelectPreview
        videoId="vid"
        selection={makeSelection("llm")}
        mode="both"
        isLoading={false}
      />,
    );
    expect(screen.getByText("AI 선택")).toBeInTheDocument();
  });

  it("does not show chip when scorer=pure", () => {
    render(
      <AutoSelectPreview
        videoId="vid"
        selection={makeSelection("pure")}
        mode="both"
        isLoading={false}
      />,
    );
    expect(screen.queryByText("AI 선택")).not.toBeInTheDocument();
  });

  it("defaults to pure (no chip) when scorer field absent for back-compat", () => {
    render(
      <AutoSelectPreview
        videoId="vid"
        selection={makeSelection(undefined)}
        mode="both"
        isLoading={false}
      />,
    );
    expect(screen.queryByText("AI 선택")).not.toBeInTheDocument();
  });
});
