import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
// jest-dom matchers loaded via vitest.setup.ts
import { CandidateCard } from "@/features/videos/components/CandidateCard";
import { ShortsPlanPanel } from "@/features/videos/components/ShortsPlanPanel";
import { ExportDialog } from "@/features/videos/components/ExportDialog";
import type { ShortsCandidateResponse } from "@/lib/types";
import { generateShortsPlan } from "@/lib/api/shorts";
import { exportToPremiere } from "@/lib/agent-export";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    getAccessToken: vi.fn().mockResolvedValue("test-token"),
    isAuthenticated: true,
    isLoading: false,
    user: { email: "test@test.com", name: "Test" },
    error: null,
    login: vi.fn(),
    loginWithCredentials: vi.fn(),
    logout: vi.fn(),
    isAuth0Enabled: false,
  }),
}));

vi.mock("@/lib/api/shorts", () => ({
  generateShortsPlan: vi.fn(),
}));

vi.mock("@/lib/agent-export", () => ({
  exportToPremiere: vi.fn(),
}));

const sampleCandidate: ShortsCandidateResponse = {
  candidate_id: "cand-1",
  video_id: "video-abc-123",
  scene_ids: ["scene_0", "scene_1"],
  start_ms: 5000,
  end_ms: 45000,
  title_suggestion: "Fashion Intro Segment",
  reason: "High transcript density with product mentions",
  score: 0.85,
  tags: ["fashion", "unboxing"],
  product_refs: ["product-a"],
  people_refs: ["person-1"],
  transcript_snippet: "Hello everyone, welcome to the live show.",
};

const secondCandidate: ShortsCandidateResponse = {
  ...sampleCandidate,
  candidate_id: "cand-2",
  scene_ids: ["scene_2"],
  start_ms: 46000,
  end_ms: 70000,
  title_suggestion: "Product Demo Highlight",
  score: 0.8,
  tags: ["demo"],
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.mocked(generateShortsPlan).mockReset();
  vi.mocked(exportToPremiere).mockReset();
});

describe("CandidateCard", () => {
  it("renders rank, score, title, time range", () => {
    render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={true}
        onToggle={vi.fn()}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("★ 0.85")).toBeInTheDocument();
    expect(screen.getByText("Fashion Intro Segment")).toBeInTheDocument();
    expect(screen.getByText("0:05 - 0:45")).toBeInTheDocument();
  });

  it("renders tags", () => {
    render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={true}
        onToggle={vi.fn()}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByText("fashion")).toBeInTheDocument();
    expect(screen.getByText("unboxing")).toBeInTheDocument();
  });

  it("renders transcript snippet", () => {
    render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={true}
        onToggle={vi.fn()}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByText("Hello everyone, welcome to the live show.")).toBeInTheDocument();
  });

  it("checkbox reflects isSelected prop", () => {
    const { rerender } = render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={true}
        onToggle={vi.fn()}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByRole("checkbox")).toBeChecked();

    rerender(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={false}
        onToggle={vi.fn()}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("calls onToggle when checkbox clicked", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();
    render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={false}
        onToggle={onToggle}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    await user.click(screen.getByRole("checkbox"));
    expect(onToggle).toHaveBeenCalled();
  });

  it("play button enabled when agentAvailable", () => {
    render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={false}
        onToggle={vi.fn()}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByRole("button", { name: "Play" })).toBeEnabled();
  });

  it("play button disabled when agent offline", () => {
    render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={false}
        onToggle={vi.fn()}
        agentAvailable={false}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByRole("button", { name: "Play" })).toBeDisabled();
  });
});

describe("ShortsPlanPanel", () => {
  it("renders Generate Shorts Plan button in idle state", () => {
    render(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={true}
      />,
    );

    expect(screen.getByRole("button", { name: "Generate Shorts Plan" })).toBeInTheDocument();
  });

  it("shows Generating... when loading", async () => {
    const user = userEvent.setup();
    vi.mocked(generateShortsPlan).mockImplementation(
      () => new Promise(() => undefined),
    );

    render(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={true}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Generate Shorts Plan" }));
    expect(screen.getByRole("button", { name: "Generating..." })).toBeDisabled();
  });

  it("shows error banner when plan fails", async () => {
    const user = userEvent.setup();
    vi.mocked(generateShortsPlan).mockRejectedValue(new Error("Plan failed"));

    render(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={true}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Generate Shorts Plan" }));
    expect(await screen.findByText("Failed to generate shorts plan")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try Again" })).toBeInTheDocument();
  });

  it("renders candidates after successful generation", async () => {
    const user = userEvent.setup();
    vi.mocked(generateShortsPlan).mockResolvedValue({
      video_id: "video-abc-123",
      video_title: "Spring Campaign",
      total_scenes: 5,
      eligible_scenes: 3,
      candidates: [sampleCandidate, secondCandidate],
    });

    render(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={true}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Generate Shorts Plan" }));
    expect(await screen.findByText("Fashion Intro Segment")).toBeInTheDocument();
    expect(screen.getByText("Product Demo Highlight")).toBeInTheDocument();
    expect(screen.getByText("2 candidates from 3 eligible scenes (5 total)")).toBeInTheDocument();
  });

  it("select all selects all candidates", async () => {
    const user = userEvent.setup();
    vi.mocked(generateShortsPlan).mockResolvedValue({
      video_id: "video-abc-123",
      video_title: "Spring Campaign",
      total_scenes: 5,
      eligible_scenes: 3,
      candidates: [sampleCandidate, secondCandidate],
    });

    render(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={true}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Generate Shorts Plan" }));
    await screen.findByText("Fashion Intro Segment");

    await user.click(screen.getByRole("button", { name: "Deselect All" }));
    expect(screen.getByText("0 selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select All" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
  });

  it("export button disabled when nothing selected", async () => {
    const user = userEvent.setup();
    vi.mocked(generateShortsPlan).mockResolvedValue({
      video_id: "video-abc-123",
      video_title: "Spring Campaign",
      total_scenes: 5,
      eligible_scenes: 3,
      candidates: [sampleCandidate, secondCandidate],
    });

    render(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={true}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Generate Shorts Plan" }));
    await screen.findByText("Fashion Intro Segment");
    await user.click(screen.getByRole("button", { name: "Deselect All" }));
    expect(screen.getByRole("button", { name: "Export to Premiere" })).toBeDisabled();
  });

  it("export button disabled when agent offline", async () => {
    const user = userEvent.setup();
    vi.mocked(generateShortsPlan).mockResolvedValue({
      video_id: "video-abc-123",
      video_title: "Spring Campaign",
      total_scenes: 5,
      eligible_scenes: 3,
      candidates: [sampleCandidate],
    });

    render(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={false}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Generate Shorts Plan" }));
    await screen.findByText("Fashion Intro Segment");
    expect(screen.getByRole("button", { name: "Export to Premiere" })).toBeDisabled();
    expect(screen.getByText("(Agent offline)")).toBeInTheDocument();
  });
});

describe("ExportDialog", () => {
  it("renders form fields when open", () => {
    render(
      <ExportDialog
        isOpen={true}
        onClose={vi.fn()}
        onExport={vi.fn()}
        selectedCount={2}
        isExporting={false}
        defaultProjectName="Spring Campaign Shorts"
      />,
    );

    expect(screen.getByText("Premiere Pro 내보내기")).toBeInTheDocument();
    expect(screen.getByLabelText("프로젝트 이름")).toBeInTheDocument();
    expect(screen.getByLabelText("저장 위치")).toBeInTheDocument();
    expect(screen.getByLabelText("프레임 레이트")).toBeInTheDocument();
    expect(screen.getByText(/2개 선택됨/)).toBeInTheDocument();
  });

  it("export button disabled when project name empty", async () => {
    const user = userEvent.setup();
    render(
      <ExportDialog
        isOpen={true}
        onClose={vi.fn()}
        onExport={vi.fn()}
        selectedCount={2}
        isExporting={false}
        defaultProjectName="Spring Campaign Shorts"
      />,
    );

    await user.clear(screen.getByLabelText("프로젝트 이름"));
    expect(screen.getByRole("button", { name: "내보내기" })).toBeDisabled();
  });

  it("export button disabled when output dir empty", async () => {
    const user = userEvent.setup();
    render(
      <ExportDialog
        isOpen={true}
        onClose={vi.fn()}
        onExport={vi.fn()}
        selectedCount={2}
        isExporting={false}
        defaultProjectName="Spring Campaign Shorts"
      />,
    );

    await user.clear(screen.getByLabelText("저장 위치"));
    expect(screen.getByRole("button", { name: "내보내기" })).toBeDisabled();
  });

  it("calls onExport with form values when export clicked", async () => {
    const user = userEvent.setup();
    const onExport = vi.fn();
    render(
      <ExportDialog
        isOpen={true}
        onClose={vi.fn()}
        onExport={onExport}
        selectedCount={2}
        isExporting={false}
        defaultProjectName="Spring Campaign Shorts"
      />,
    );

    await user.selectOptions(screen.getByLabelText("프레임 레이트"), "30");
    await user.click(screen.getByRole("button", { name: "내보내기" }));

    expect(onExport).toHaveBeenCalledWith({
      projectName: "Spring Campaign Shorts",
      outputDir: "~/Desktop/Heimdex Exports",
      frameRate: 30,
    });
  });

  it("closes on cancel click", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <ExportDialog
        isOpen={true}
        onClose={onClose}
        onExport={vi.fn()}
        selectedCount={2}
        isExporting={false}
        defaultProjectName="Spring Campaign Shorts"
      />,
    );

    await user.click(screen.getByRole("button", { name: "취소" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("does not render when isOpen is false", () => {
    const { container } = render(
      <ExportDialog
        isOpen={false}
        onClose={vi.fn()}
        onExport={vi.fn()}
        selectedCount={2}
        isExporting={false}
        defaultProjectName="Spring Campaign Shorts"
      />,
    );

    expect(container.innerHTML).toBe("");
  });
});
