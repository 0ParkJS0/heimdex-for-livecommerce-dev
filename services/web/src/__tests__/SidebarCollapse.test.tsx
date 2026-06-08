import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopHeader } from "@/components/layout/TopHeader";
const mockUsePathname = vi.fn(() => "/");

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() }),
  usePathname: () => mockUsePathname(),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    getAccessToken: vi.fn().mockResolvedValue("token"),
    user: { name: "Test User", email: "test@test.com" },
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/api/devices", () => ({
  getDevices: vi.fn().mockResolvedValue({ devices: [] }),
}));

// figma 1607:67462 (expanded) / 1670:185900 (collapsed 64px rail).
describe("Sidebar — redesigned LNB", () => {
  beforeEach(() => {
    mockUsePathname.mockReturnValue("/");
  });

  it("renders the 메인 / 라이브러리 sections with their items when expanded", () => {
    render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    expect(screen.getByText("메인")).toBeInTheDocument();
    expect(screen.getByText("라이브러리")).toBeInTheDocument();
    expect(screen.getByText("동영상 검색")).toBeInTheDocument();
    expect(screen.getByText("이미지 검색")).toBeInTheDocument();
    expect(screen.getByText("인물 라벨 관리")).toBeInTheDocument();
    expect(screen.getByText("교차 편집")).toBeInTheDocument();
    expect(screen.getByText("내 쇼츠")).toBeInTheDocument();
    expect(screen.getByText("설정")).toBeInTheDocument();
  });

  it("no longer renders the removed menus or the Pro badge", () => {
    render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    expect(screen.queryByText("파일 동기화")).not.toBeInTheDocument();
    expect(screen.queryByText("내보내기")).not.toBeInTheDocument();
    expect(screen.queryByText("문서")).not.toBeInTheDocument();
    expect(screen.queryByText("에이전트")).not.toBeInTheDocument();
    expect(screen.queryByText("Pro")).not.toBeInTheDocument();
  });

  it("routes the renamed items to the correct hrefs", () => {
    render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    expect(screen.getByText("동영상 검색").closest("a")).toHaveAttribute("href", "/");
    expect(screen.getByText("교차 편집").closest("a")).toHaveAttribute(
      "href",
      "/export/preedit",
    );
    expect(screen.getByText("내 쇼츠").closest("a")).toHaveAttribute(
      "href",
      "/export/shorts",
    );
  });

  it("collapses to a 64px rail (not fully hidden) with icon-only links", () => {
    const { container } = render(<Sidebar collapsed={true} onToggle={vi.fn()} />);

    const aside = container.querySelector("aside");
    expect(aside).toHaveClass("w-16");
    expect(aside).not.toHaveClass("w-0");
    expect(aside).not.toHaveClass("overflow-hidden");

    // Labels collapse to aria-label/title; visible text is gone.
    expect(screen.queryByText("동영상 검색")).not.toBeInTheDocument();
    expect(screen.getByLabelText("동영상 검색")).toBeInTheDocument();
  });

  it("applies w-[270px] when expanded", () => {
    const { container } = render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    const aside = container.querySelector("aside");
    expect(aside).toHaveClass("w-[270px]");
    expect(aside).not.toHaveClass("overflow-hidden");
  });

  it("has transition classes for smooth animation", () => {
    const { container } = render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    const aside = container.querySelector("aside");
    expect(aside).toHaveClass("transition-[width]");
    expect(aside).toHaveClass("duration-300");
    expect(aside).toHaveClass("ease-in-out");
  });

  it("calls onToggle when the collapse button is clicked", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();

    render(<Sidebar collapsed={false} onToggle={onToggle} />);

    await user.click(screen.getByLabelText("사이드바 접기"));

    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("calls onToggle when the rail expand button is clicked", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();

    render(<Sidebar collapsed={true} onToggle={onToggle} />);

    await user.click(screen.getByLabelText("사이드바 펼치기"));

    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("highlights the active item via the pathname", () => {
    mockUsePathname.mockReturnValue("/export/preedit");
    render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    expect(screen.getByText("교차 편집").closest("a")).toHaveClass("bg-neutral-h-100");
  });
});

describe("TopHeader — no reopen button after rail unification", () => {
  it("no longer renders the sidebar reopen button", () => {
    render(<TopHeader />);

    expect(screen.queryByLabelText("사이드바 열기")).not.toBeInTheDocument();
  });
});

describe("localStorage persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("stores collapsed state in localStorage", () => {
    localStorage.setItem("heimdex-sidebar-collapsed", "true");
    expect(localStorage.getItem("heimdex-sidebar-collapsed")).toBe("true");
  });

  it("defaults to expanded when localStorage is empty", () => {
    expect(localStorage.getItem("heimdex-sidebar-collapsed")).toBeNull();
  });

  it("stores expanded state as 'false'", () => {
    localStorage.setItem("heimdex-sidebar-collapsed", "false");
    expect(localStorage.getItem("heimdex-sidebar-collapsed")).toBe("false");
  });
});
