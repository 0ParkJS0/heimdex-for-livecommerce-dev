import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

type ViewMode = "overview" | "scenes" | "people";

const mockReplace = vi.fn();
const mockPush = vi.fn();
let mockSearchParams = new URLSearchParams();

// Stable function reference — MUST NOT be recreated per render to avoid useEffect infinite loop
const mockGetAccessToken = vi.fn().mockResolvedValue("token");

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, back: vi.fn(), replace: mockReplace }),
  useSearchParams: () => mockSearchParams,
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    getAccessToken: mockGetAccessToken,
    user: { name: "Test", email: "t@t.com" },
    isAuthenticated: true,
    isLoading: false,
  }),
}));

vi.mock("@/features/search/hooks/useAgent", () => ({
  useAgent: () => ({ isAvailable: false }),
}));

vi.mock("@/lib/orgSettings", () => ({
  useOrgSettings: () => ({ settings: { thumbnail_aspect_ratio: "16:9" } }),
  OrgSettingsProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Scene response data inlined to avoid hoisting issues with vi.mock
vi.mock("@/lib/api/videos", () => ({
  getVideoScenes: vi.fn().mockResolvedValue({
    video_title: "Test Video",
    total: 25,
    scenes: Array.from({ length: 25 }, (_, i) => ({
      scene_id: `s${i}`,
      start_ms: i * 10000,
      end_ms: (i + 1) * 10000,
      transcript_raw: "",
      transcript_char_count: 0,
      keyword_tags: [],
      product_tags: [],
      product_entities: [],
      speech_segment_count: 0,
      people_cluster_ids: [],
      ingest_time: null,
      keyframe_timestamp_ms: i * 10000,
    })),
  }),
  getAllVideoScenes: vi.fn().mockResolvedValue({
    video_title: "Test Video",
    total: 25,
    scenes: Array.from({ length: 25 }, (_, i) => ({
      scene_id: `s${i}`,
      start_ms: i * 10000,
      end_ms: (i + 1) * 10000,
      transcript_raw: "",
      transcript_char_count: 0,
      keyword_tags: [],
      product_tags: [],
      product_entities: [],
      speech_segment_count: 0,
      people_cluster_ids: [],
      ingest_time: null,
      keyframe_timestamp_ms: i * 10000,
    })),
  }),
  getReprocessStatus: vi.fn().mockResolvedValue(null),
  reprocessScenes: vi.fn(),
  patchSceneOverride: vi.fn(),
  resetSceneOverride: vi.fn(),
  getVideoSummary: vi.fn().mockResolvedValue(null),
  generateVideoSummary: vi.fn().mockResolvedValue(null),
  editVideoSummary: vi.fn(),
  resetVideoSummary: vi.fn(),
  getVideoPeople: vi.fn().mockResolvedValue({ people: [] }),
}));

vi.mock("@/lib/api/people", () => ({
  renamePerson: vi.fn(),
  deletePerson: vi.fn(),
}));

vi.mock("@/lib/agent", () => ({
  getAgentPlaybackUrl: vi.fn().mockReturnValue(""),
  getAgentThumbnailUrl: vi.fn().mockReturnValue(""),
  getCloudPlaybackUrl: vi.fn().mockReturnValue(""),
  getCloudThumbnailUrl: vi.fn().mockReturnValue(""),
  getFaceThumbnailUrl: vi.fn().mockReturnValue(""),
}));

vi.mock("@/components/SceneThumbnail", () => ({
  SceneThumbnail: () => <div data-testid="thumb">thumb</div>,
}));

vi.mock("@/components/OpenInDriveButton", () => ({
  OpenInDriveButton: () => null,
}));

vi.mock("@/features/videos/hooks/useSceneGroups", () => ({
  useSceneGroups: () => ({ groups: null, isLoading: false, error: null, fetchGroups: vi.fn() }),
}));

vi.mock("@/features/shorts-auto", () => ({
  AutoShortsCTA: ({ onClick }: { onClick?: () => void }) => (
    <button type="button" onClick={onClick}>AI 쇼츠 생성</button>
  ),
}));

vi.mock("@/features/shorts-auto-product-wizard/components/InlineWizardContainer", () => ({
  InlineWizardContainer: () => <div data-testid="inline-wizard">wizard</div>,
}));

vi.mock("@/features/basket/useSceneBasket", () => ({
  useSceneBasket: () => ({
    items: [],
    addItem: vi.fn(),
    removeItem: vi.fn(),
    clearBasket: vi.fn(),
    isInBasket: () => false,
  }),
  SceneBasketProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import { VideoDetailPage } from "@/features/videos/components/VideoDetailPage";
import { getAllVideoScenes, getVideoScenes, getReprocessStatus, getVideoPeople } from "@/lib/api/videos";

function makeSceneResponse() {
  return {
    video_title: "Test Video",
    total: 25,
    scenes: Array.from({ length: 25 }, (_, i) => ({
      scene_id: `s${i}`,
      start_ms: i * 10000,
      end_ms: (i + 1) * 10000,
      transcript_raw: "",
      transcript_char_count: 0,
      keyword_tags: [],
      product_tags: [],
      product_entities: [],
      speech_segment_count: 0,
      people_cluster_ids: [],
      ingest_time: null,
      keyframe_timestamp_ms: i * 10000,
    })),
  };
}

async function renderVideoDetail(params?: string) {
  mockSearchParams = new URLSearchParams(params ?? "");
  const result = render(<VideoDetailPage videoId="test-video-123" />);
  await screen.findAllByText("Test Video", {}, { timeout: 5000 });
  return result;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGetAccessToken.mockResolvedValue("token");
  vi.mocked(getVideoScenes).mockResolvedValue(makeSceneResponse() as any);
  vi.mocked(getAllVideoScenes).mockResolvedValue(makeSceneResponse() as any);
  vi.mocked(getReprocessStatus).mockResolvedValue(null);
  vi.mocked(getVideoPeople).mockResolvedValue({ people: [] } as any);
  mockSearchParams = new URLSearchParams();
  Object.defineProperty(window, "location", {
    value: { pathname: "/videos/test-video-123", search: "", href: "http://localhost/videos/test-video-123" },
    writable: true,
  });
});

describe("VideoDetailPage tab bar", () => {
  it("renders three tabs and AI shorts button", async () => {
    await renderVideoDetail();

    expect(screen.getByRole("button", { name: /개요/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /장면 분석/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /인물 관리/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /AI 쇼츠 생성/ })).toBeInTheDocument();
  });

  it("renders scenes tab without count badge", async () => {
    await renderVideoDetail();

    const scenesTab = screen.getByRole("button", { name: /장면 분석/ });
    expect(scenesTab.textContent?.replace(/장면\s*분석/g, "").trim()).toBe("");
  });

  it("defaults to overview tab when no URL params", async () => {
    await renderVideoDetail();

    const overviewTab = screen.getByRole("button", { name: /개요/ });
    expect(overviewTab).toHaveClass("border-heimdex-navy-500");
  });

  it("initializes to scenes tab when ?view=scenes", async () => {
    await renderVideoDetail("view=scenes");

    const scenesTab = screen.getByRole("button", { name: /장면 분석/ });
    expect(scenesTab).toHaveClass("border-heimdex-navy-500");
  });

  it("initializes to people tab when ?view=people", async () => {
    await renderVideoDetail("view=people");

    const peopleTab = screen.getByRole("button", { name: /인물 관리/ });
    expect(peopleTab).toHaveClass("border-heimdex-navy-500");
  });

  it("?t= parameter overrides ?view= and forces scenes tab", async () => {
    await renderVideoDetail("t=5000&view=people");

    const scenesTab = screen.getByRole("button", { name: /장면 분석/ });
    expect(scenesTab).toHaveClass("border-heimdex-navy-500");
  });

  it("switches view when tab is clicked", async () => {
    const user = userEvent.setup();
    await renderVideoDetail();

    // Click scenes tab
    await user.click(screen.getByRole("button", { name: /장면 분석/ }));
    expect(screen.getByRole("button", { name: /장면 분석/ })).toHaveClass("border-heimdex-navy-500");

    // Click people tab
    await user.click(screen.getByRole("button", { name: /인물 관리/ }));
    expect(screen.getByRole("button", { name: /인물 관리/ })).toHaveClass("border-heimdex-navy-500");

    // Click back to overview
    await user.click(screen.getByRole("button", { name: /개요/ }));
    expect(screen.getByRole("button", { name: /개요/ })).toHaveClass("border-heimdex-navy-500");
  });

  it("updates URL when switching tabs via router.replace", async () => {
    const user = userEvent.setup();
    await renderVideoDetail();

    await user.click(screen.getByRole("button", { name: /장면 분석/ }));
    expect(mockReplace).toHaveBeenCalledWith(
      expect.stringContaining("view=scenes"),
      { scroll: false },
    );
  });

  it("paginates scene analysis with backend offsets instead of local first-page slicing", async () => {
    const user = userEvent.setup();
    vi.mocked(getVideoScenes).mockImplementation(async (_videoId, pageSize, offset) => ({
      ...makeSceneResponse(),
      total: 604,
      scenes: Array.from({ length: pageSize ?? 10 }, (_, i) => {
        const n = (offset ?? 0) + i;
        return {
          scene_id: `s${n}`,
          start_ms: n * 10000,
          end_ms: (n + 1) * 10000,
          transcript_raw: "",
          transcript_char_count: 0,
          keyword_tags: [],
          product_tags: [],
          product_entities: [],
          speech_segment_count: 0,
          people_cluster_ids: [],
          ingest_time: null,
          keyframe_timestamp_ms: n * 10000,
        };
      }),
    }) as any);
    vi.mocked(getAllVideoScenes).mockResolvedValue({
      ...makeSceneResponse(),
      total: 604,
      scenes: [],
    } as any);

    await renderVideoDetail("view=scenes");

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "61 페이지" })).toBeInTheDocument();
    });
    expect(
      vi.mocked(getVideoScenes).mock.calls.filter(
        ([videoId, pageSize, offset]) =>
          videoId === "test-video-123" && pageSize === 10 && offset === 0,
      ),
    ).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "다음 페이지" }));

    await waitFor(() => {
      expect(getVideoScenes).toHaveBeenCalledWith(
        "test-video-123",
        10,
        10,
        mockGetAccessToken,
        undefined,
      );
    });
  });

  it("removes view param from URL when switching to overview", async () => {
    const user = userEvent.setup();
    Object.defineProperty(window, "location", {
      value: { pathname: "/videos/test-video-123", search: "?view=scenes", href: "http://localhost/videos/test-video-123?view=scenes" },
      writable: true,
    });
    await renderVideoDetail("view=scenes");

    await user.click(screen.getByRole("button", { name: /개요/ }));
    expect(mockReplace).toHaveBeenCalledWith(
      "/videos/test-video-123",
      { scroll: false },
    );
  });

  it("AI shorts button switches to auto-shorts view", async () => {
    const user = userEvent.setup();
    await renderVideoDetail();

    await user.click(screen.getByRole("button", { name: /AI 쇼츠 생성/ }));
    expect(mockReplace).toHaveBeenCalledWith(
      expect.stringContaining("view=auto-shorts"),
      { scroll: false },
    );
  });

  it("ignores invalid ?view= values and defaults to overview", async () => {
    await renderVideoDetail("view=invalid");

    const overviewTab = screen.getByRole("button", { name: /개요/ });
    expect(overviewTab).toHaveClass("border-heimdex-navy-500");
  });

  it("renders simplified breadcrumb with video title only", async () => {
    await renderVideoDetail();

    // Breadcrumb shows video title (appears in both breadcrumb + heading)
    const breadcrumbs = screen.getAllByText("Test Video");
    expect(breadcrumbs.length).toBeGreaterThanOrEqual(1);

    // No view-specific breadcrumb text
    expect(screen.queryByText("영상 장면 분석")).not.toBeInTheDocument();
  });
});
