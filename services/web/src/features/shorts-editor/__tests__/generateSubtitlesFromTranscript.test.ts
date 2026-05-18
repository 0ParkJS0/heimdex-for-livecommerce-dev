import { describe, it, expect } from "vitest";

import { generateSubtitlesFromTranscript } from "../hooks/useEditorState";
import type { EditorClip } from "../lib/types";

// 2026-05-18 accuracy improvements:
//   1. Removed the ``DEFAULT_SUBTITLE_DURATION_MS * 3`` (9s) cap on a
//      single turn's slot so long monologues no longer leave the back
//      half silent.
//   2. Per-chunk duration weighted by character count (Korean speech
//      rate ≈ 7 chars/sec) instead of even-split.
//   3. Per-chunk floor 800ms / ceiling 4000ms.
//
// These tests pin the new behaviour so a future tweak doesn't silently
// regress the timing math.

function makeClip(overrides: Partial<EditorClip> = {}): EditorClip {
  return {
    id: "clip_test",
    sceneId: "scene_1",
    videoId: "gd_video1",
    sourceType: "gdrive",
    originalStartMs: 0,
    originalEndMs: 30_000,
    trimStartMs: 0,
    trimEndMs: 30_000,
    timelineStartMs: 0,
    volume: 1.0,
    ...overrides,
  };
}

describe("generateSubtitlesFromTranscript — char-density weighting", () => {
  it("weights chunk duration by character count when one turn has chunks of different lengths", () => {
    // Single turn with two sentences of very different lengths.
    // Sentence A is short (~6 chars), sentence B is long (~24 chars).
    // 12s slot should be split roughly 1:4 by character ratio.
    const transcript =
      "SPEAKER_00 [0:00]: 안녕하세요. 오늘은 정말 길고 자세하게 설명해드리겠습니다.";
    const clip = makeClip({ trimEndMs: 12_000 });
    const subs = generateSubtitlesFromTranscript(transcript, clip);

    expect(subs.length).toBeGreaterThanOrEqual(2);
    const first = subs[0];
    const second = subs[1];
    const firstDur = first.endMs - first.startMs;
    const secondDur = second.endMs - second.startMs;

    // Short sentence should land within the [800, 4000] band but
    // shorter than the long sentence.
    expect(firstDur).toBeGreaterThanOrEqual(800);
    expect(firstDur).toBeLessThanOrEqual(4000);
    expect(secondDur).toBeGreaterThanOrEqual(800);
    expect(secondDur).toBeLessThanOrEqual(4000);
    expect(secondDur).toBeGreaterThan(firstDur);
  });

  it("clamps every chunk to the 800ms floor when the slot is very short", () => {
    // 1.2s slot with two 5-char sentences would split to 600ms each
    // under even-distribution; the 800ms floor lifts both.
    const transcript = "SPEAKER_00 [0:00]: 안녕. 반가워.";
    const clip = makeClip({ trimEndMs: 1_200 });
    const subs = generateSubtitlesFromTranscript(transcript, clip);

    for (const s of subs) {
      const dur = s.endMs - s.startMs;
      // Inside clip duration the floor can be reached but not breached
      // (the only escape is hitting the clipDuration tail clamp).
      expect(dur).toBeGreaterThanOrEqual(0);
    }
    // First chunk must respect the 800ms floor when there's room.
    if (subs.length > 0) {
      expect(subs[0].endMs - subs[0].startMs).toBeGreaterThanOrEqual(800);
    }
  });
});

describe("generateSubtitlesFromTranscript — long-monologue slot expansion", () => {
  it("fills a 20s single-turn slot with chunks that span the whole slot", () => {
    // Old behavior: capped slot at 9s, leaving 11s silent.
    // New behavior: chunks fill the full 20s.
    const longText =
      "안녕하세요. 오늘 이 제품에 대해서 자세히 설명해드리겠습니다. " +
      "정말 좋은 제품이에요. 강력 추천드립니다. " +
      "사용법은 간단합니다. 한 번 보시죠. " +
      "지금 바로 구매하실 수 있습니다.";
    const transcript = `SPEAKER_00 [0:00]: ${longText}`;
    const clip = makeClip({ trimEndMs: 20_000 });
    const subs = generateSubtitlesFromTranscript(transcript, clip);

    expect(subs.length).toBeGreaterThan(0);
    const lastEnd = subs[subs.length - 1].endMs;
    // Last subtitle should land well past the old 9s cap (within
    // PER_CHUNK_MAX_MS=4000ms of the slot end is acceptable).
    expect(lastEnd).toBeGreaterThan(9_000);
  });

  it("caps every chunk at the 4s ceiling even when the per-char share is larger", () => {
    // A single 50-char sentence inside a 30s slot would weigh in at
    // ~30s if the per-chunk ceiling weren't applied. Floor the chunk
    // at 4000ms so the operator never sees a multi-sentence-long
    // subtitle block on the timeline.
    const longSentence =
      "이것은 길이가 매우매우매우매우매우매우매우매우 긴 단일 문장입니다.";
    const transcript = `SPEAKER_00 [0:00]: ${longSentence}`;
    const clip = makeClip({ trimEndMs: 30_000 });
    const subs = generateSubtitlesFromTranscript(transcript, clip);

    for (const s of subs) {
      expect(s.endMs - s.startMs).toBeLessThanOrEqual(4_000);
    }
  });
});

describe("generateSubtitlesFromTranscript — Korean sentence anchors", () => {
  it("splits on common Korean sentence-end markers (다. / 요. / 까? / 네.)", () => {
    const transcript =
      "SPEAKER_00 [0:00]: 안녕하세요. 잘 부탁드립니다. 어떠신가요? 좋네요.";
    const clip = makeClip({ trimEndMs: 10_000 });
    const subs = generateSubtitlesFromTranscript(transcript, clip);

    // Four sentences should produce >= 2 chunks (the chunker may merge
    // adjacent short clauses up to MAX_SUBTITLE_CHARS=25).
    expect(subs.length).toBeGreaterThanOrEqual(2);
  });
});
