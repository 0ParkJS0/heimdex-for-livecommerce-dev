import { describe, it, expect } from "vitest";
import type { EditorClip, EditorSubtitle } from "../lib/types";
import {
  splitSubtitleText,
  splitSubtitlesAtMs,
  splitClipsAtMs,
  dropAndShiftSubtitles,
  dropAndShiftClips,
  trimClipSubtitles,
} from "../lib/clip-subtitle-link";

function makeSub(
  id: string,
  startMs: number,
  endMs: number,
): EditorSubtitle {
  return {
    id,
    text: id,
    startMs,
    endMs,
    style: {
      fontFamily: "Pretendard",
      fontSizePx: 24,
      fontColor: "#fff",
      fontWeight: 700,
      positionX: 0.5,
      positionY: 0.9,
      backgroundColor: null,
      backgroundOpacity: 0,
    },
  };
}

function makeClip(
  id: string,
  timelineStartMs: number,
  trimStartMs: number,
  trimEndMs: number,
): EditorClip {
  return {
    id,
    sceneId: "s1",
    videoId: "v1",
    sourceType: "gdrive",
    originalStartMs: trimStartMs,
    originalEndMs: trimEndMs,
    trimStartMs,
    trimEndMs,
    timelineStartMs,
    volume: 1,
  };
}

describe("splitSubtitleText", () => {
  it("splits at nearest eojeol boundary before target", () => {
    // "프로젝트 마일스톤 달성을 축하드립니다" = 18 chars
    // fraction=0.55 → targetIdx=10 → nearest space before idx 10 is at 8
    // → splits between "마일스톤" and "달성을"
    const [head, tail] = splitSubtitleText(
      "프로젝트 마일스톤 달성을 축하드립니다",
      0.55,
    );
    expect(head).toBe("프로젝트 마일스톤");
    expect(tail).toBe("달성을 축하드립니다");
  });

  it("falls back to glyph split for single eojeol", () => {
    const [head, tail] = splitSubtitleText("축하드립니다", 0.5);
    expect(head).toBe("축하드");
    expect(tail).toBe("립니다");
  });

  it("returns empty pair for empty string", () => {
    const [head, tail] = splitSubtitleText("", 0.5);
    expect(head).toBe("");
    expect(tail).toBe("");
  });

  it("handles fraction=0 — all text goes to tail", () => {
    const [head, tail] = splitSubtitleText("안녕하세요", 0);
    expect(head).toBe("");
    expect(tail).toBe("안녕하세요");
  });

  it("handles fraction=1 — all text goes to head", () => {
    const [head, tail] = splitSubtitleText("안녕하세요", 1);
    expect(head).toBe("안녕하세요");
    expect(tail).toBe("");
  });

  it("splits multi-word Korean text at interior boundary", () => {
    // "신규 파트너십 체결로 사업 확장의 기회가" = 19 chars
    // fraction=0.4 → targetIdx=8 → nearest space before idx 8 is at 7
    // → splits between "파트너십" and "체결로"
    const [head, tail] = splitSubtitleText(
      "신규 파트너십 체결로 사업 확장의 기회가",
      0.4,
    );
    expect(head).toBe("신규 파트너십");
    expect(tail).toBe("체결로 사업 확장의 기회가");
  });
});

describe("splitSubtitlesAtMs", () => {
  it("splits a subtitle that straddles atMs within clip range", () => {
    const subs = [makeSub("a", 0, 4000)];
    const result = splitSubtitlesAtMs(subs, 2000, [0, 5000]);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({ id: "a", startMs: 0, endMs: 2000 });
    expect(result[1]).toMatchObject({ startMs: 2000, endMs: 4000 });
    expect(result[1].id).not.toBe("a");
  });

  it("leaves subtitle outside clip range untouched", () => {
    const subs = [makeSub("a", 6000, 9000)];
    const result = splitSubtitlesAtMs(subs, 2000, [0, 5000]);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("a");
  });

  it("no-ops when atMs is at the subtitle edge", () => {
    const subs = [makeSub("a", 0, 4000)];
    const result = splitSubtitlesAtMs(subs, 4000, [0, 5000]);
    expect(result).toHaveLength(1);
  });

  it("handles multiple subtitles, only splits the straddling one", () => {
    const subs = [makeSub("a", 0, 2000), makeSub("b", 2000, 5000), makeSub("c", 5000, 7000)];
    const result = splitSubtitlesAtMs(subs, 3000, [0, 6000]);
    expect(result).toHaveLength(4);
    expect(result[0].id).toBe("a");
    expect(result[1]).toMatchObject({ id: "b", endMs: 3000 });
    expect(result[2]).toMatchObject({ startMs: 3000, endMs: 5000 });
    expect(result[3].id).toBe("c");
  });
});

describe("splitClipsAtMs", () => {
  it("splits a clip that straddles atMs", () => {
    // clip: timeline 0-5000, source 0-5000
    const clips = [makeClip("c1", 0, 0, 5000)];
    const result = splitClipsAtMs(clips, 2000);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({ trimEndMs: 2000 });
    expect(result[1]).toMatchObject({ trimStartMs: 2000, timelineStartMs: 2000 });
    expect(result[1].id).not.toBe("c1");
  });

  it("leaves clips outside the cut untouched", () => {
    const clips = [makeClip("c1", 0, 0, 2000), makeClip("c2", 2000, 0, 3000)];
    const result = splitClipsAtMs(clips, 1000);
    // c1 straddles 1000, c2 does not
    expect(result).toHaveLength(3);
    expect(result[2].id).toBe("c2");
  });

  it("no-ops when atMs is at a clip boundary", () => {
    const clips = [makeClip("c1", 0, 0, 2000)];
    const result = splitClipsAtMs(clips, 0);
    expect(result).toHaveLength(1);
  });
});

describe("dropAndShiftSubtitles", () => {
  it("drops subtitles fully inside removed window", () => {
    const subs = [makeSub("a", 1000, 3000)];
    const result = dropAndShiftSubtitles(subs, 0, 5000);
    expect(result).toHaveLength(0);
  });

  it("keeps subtitles fully before removed window unchanged", () => {
    const subs = [makeSub("a", 0, 500)];
    const result = dropAndShiftSubtitles(subs, 1000, 3000);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ startMs: 0, endMs: 500 });
  });

  it("shifts subtitles fully after removed window left by removed duration", () => {
    const subs = [makeSub("a", 5000, 7000)];
    const result = dropAndShiftSubtitles(subs, 1000, 3000); // removed 2000ms
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ startMs: 3000, endMs: 5000 });
  });

  it("trims subtitle that straddles removeStart", () => {
    const subs = [makeSub("a", 500, 2000)];
    const result = dropAndShiftSubtitles(subs, 1000, 3000);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ startMs: 500, endMs: 1000 });
  });

  it("repositions subtitle that straddles removeEnd", () => {
    const subs = [makeSub("a", 2000, 5000)];
    const result = dropAndShiftSubtitles(subs, 1000, 3000); // removed 2000ms
    expect(result).toHaveLength(1);
    // starts at removeStart, end shifted left by 2000ms
    expect(result[0]).toMatchObject({ startMs: 1000, endMs: 3000 });
  });
});

describe("dropAndShiftClips", () => {
  it("drops clips fully inside removed window", () => {
    const clips = [makeClip("c1", 1000, 0, 2000)]; // timeline 1000-3000
    const result = dropAndShiftClips(clips, 0, 5000);
    expect(result).toHaveLength(0);
  });

  it("keeps clips fully before removed window unchanged", () => {
    const clips = [makeClip("c1", 0, 0, 500)];
    const result = dropAndShiftClips(clips, 1000, 3000);
    expect(result).toHaveLength(1);
    expect(result[0].timelineStartMs).toBe(0);
  });

  it("shifts clips fully after removed window", () => {
    const clips = [makeClip("c1", 5000, 0, 2000)];
    const result = dropAndShiftClips(clips, 1000, 3000); // 2000ms removed
    expect(result).toHaveLength(1);
    expect(result[0].timelineStartMs).toBe(3000);
  });
});

describe("trimClipSubtitles (non-destructive)", () => {
  it("preserves subtitle within clip window (no clamping)", () => {
    // Clip old: 0-5000, new: 0-4000 (trimmed 1000 from end)
    // Subtitle 0-800 is within the clip — kept as-is.
    const subs = [makeSub("a", 0, 800)];
    const result = trimClipSubtitles(subs, 0, 5000, 0, 4000);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ startMs: 0, endMs: 800 });
  });

  it("preserves subtitle past trim-end (non-destructive — not dropped)", () => {
    // Clip old: 0-5000, new: 0-3000 (trimmed 2000 from end)
    // Subtitle 3500-4500 is past the new clip end but is preserved.
    // Render-time filtering hides it; extending the trim restores it.
    const subs = [makeSub("a", 3500, 4500)];
    const result = trimClipSubtitles(subs, 0, 5000, 0, 3000);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ startMs: 3500, endMs: 4500 });
  });

  it("preserves subtitle straddling trim-end (no clamping)", () => {
    // Clip old: 0-5000, new: 0-3000 (trimmed 2000 from end)
    // Subtitle 2000-4000 straddles the new end — kept as-is.
    const subs = [makeSub("a", 2000, 4000)];
    const result = trimClipSubtitles(subs, 0, 5000, 0, 3000);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ startMs: 2000, endMs: 4000 });
  });

  it("preserves downstream subtitles unchanged (no shifting)", () => {
    // Clip old: 0-5000, new: 0-3000 (trimmed 2000 from end)
    // Subtitle after clip is preserved unchanged — gaps are allowed.
    const subs = [makeSub("a", 6000, 8000)];
    const result = trimClipSubtitles(subs, 0, 5000, 0, 3000);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ startMs: 6000, endMs: 8000 });
  });

  it("preserves subtitle in trimmed-off start portion (non-destructive)", () => {
    // Subtitle 0-1500 falls in the trimmed-off region but is preserved.
    const subs = [makeSub("a", 0, 1500)];
    const result = trimClipSubtitles(subs, 0, 5000, 0, 3000);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ startMs: 0, endMs: 1500 });
  });

  it("keeps subtitles before the clip unchanged", () => {
    const subs = [makeSub("before", 0, 500)];
    // Clip at 1000-5000, trimmed to 1000-3000
    const result = trimClipSubtitles(subs, 1000, 5000, 1000, 3000);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ startMs: 0, endMs: 500 });
  });

  it("no-ops when no trim delta", () => {
    const subs = [makeSub("a", 0, 3000)];
    const result = trimClipSubtitles(subs, 0, 5000, 0, 5000);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ startMs: 0, endMs: 3000 });
  });

  it("grow-back restores subtitles that were previously hidden", () => {
    // Trim down: 0-5000 → 0-3000 (2000ms trimmed from end)
    const subs = [makeSub("a", 3500, 4500)];
    const trimmed = trimClipSubtitles(subs, 0, 5000, 0, 3000);
    // Subtitle preserved (non-destructive)
    expect(trimmed).toHaveLength(1);
    // Grow back: 0-3000 → 0-5000 (restore the 2000ms)
    const restored = trimClipSubtitles(trimmed, 0, 3000, 0, 5000);
    // Still there, unchanged
    expect(restored).toHaveLength(1);
    expect(restored[0]).toMatchObject({ startMs: 3500, endMs: 4500 });
  });

  it("trim-shrink preserves downstream subtitles unchanged", () => {
    // Clip old: 0-10000, new: 0-7000 (trimmed 3000 from end).
    // Downstream subtitle at 15000-17000 stays unchanged — no shifting.
    const subs = [
      makeSub("inside", 2000, 4000),
      makeSub("downstream", 15000, 17000),
    ];
    const result = trimClipSubtitles(subs, 0, 10000, 0, 7000);
    expect(result).toHaveLength(2);
    // Inside subtitle preserved (non-destructive)
    expect(result[0]).toMatchObject({ startMs: 2000, endMs: 4000 });
    // Downstream subtitle preserved unchanged (gaps allowed)
    expect(result[1]).toMatchObject({ startMs: 15000, endMs: 17000 });
  });

  it("trim-shrink from start preserves downstream subtitles unchanged", () => {
    // Clip old: 5000-10000, new: 5000-8000. Downstream subtitle at
    // 12000-13000 stays unchanged — no shifting.
    const subs = [makeSub("downstream", 12000, 13000)];
    const result = trimClipSubtitles(subs, 5000, 10000, 5000, 8000);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ startMs: 12000, endMs: 13000 });
  });
});
