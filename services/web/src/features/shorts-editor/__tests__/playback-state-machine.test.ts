import { describe, it, expect } from "vitest";
import { reducePlayback } from "../hooks/useEditorState";
import type { Playback, PlaybackEvent, PlaybackRate } from "../lib/types";

const idle: Playback = { kind: "idle" };
const playing1: Playback = { kind: "playing", rate: 1 };
const playing2: Playback = { kind: "playing", rate: 2 };
const playing4: Playback = { kind: "playing", rate: 4 };
const playing8: Playback = { kind: "playing", rate: 8 };
const paused = (ms: number, r: PlaybackRate = 1): Playback => ({
  kind: "paused",
  pausedAtMs: ms,
  resumeRate: r,
});
const seeking = (from: number, to: number, resume: Playback): Playback => ({
  kind: "seeking",
  from,
  to,
  resume,
});

const TOGGLE: PlaybackEvent = { kind: "TOGGLE" };
const PLAY_FWD: PlaybackEvent = { kind: "PLAY_FORWARD" };
const PLAY_BWD: PlaybackEvent = { kind: "PLAY_BACKWARD_OR_SLOW" };
const HARD_PAUSE: PlaybackEvent = { kind: "HARD_PAUSE" };
const seekEv = (toMs: number): PlaybackEvent => ({ kind: "SEEK", toMs });
const SEEK_DONE: PlaybackEvent = { kind: "SEEK_DONE" };
const REACHED_END: PlaybackEvent = { kind: "REACHED_END" };
const setRate = (rate: PlaybackRate): PlaybackEvent => ({ kind: "SET_RATE", rate });

// Helper — reduces and returns the new state
function reduce(pb: Playback, event: PlaybackEvent, playheadMs = 5000, totalMs = 10000): Playback {
  return reducePlayback(pb, event, playheadMs, totalMs);
}

describe("Playback State Machine", () => {
  // ─── idle ───────────────────────────────────────────────
  describe("idle state", () => {
    it("TOGGLE → playing(1)", () => {
      expect(reduce(idle, TOGGLE)).toEqual(playing1);
    });

    it("PLAY_FORWARD → playing(1)", () => {
      expect(reduce(idle, PLAY_FWD)).toEqual(playing1);
    });

    it("PLAY_BACKWARD_OR_SLOW → stays idle (jog handled externally)", () => {
      expect(reduce(idle, PLAY_BWD)).toBe(idle);
    });

    it("HARD_PAUSE → stays idle", () => {
      expect(reduce(idle, HARD_PAUSE)).toBe(idle);
    });

    it("SEEK → seeking(0→to, resume=idle)", () => {
      expect(reduce(idle, seekEv(3000))).toEqual(seeking(0, 3000, idle));
    });

    it("SEEK_DONE → stays idle (n/a)", () => {
      expect(reduce(idle, SEEK_DONE)).toBe(idle);
    });

    it("REACHED_END → stays idle", () => {
      expect(reduce(idle, REACHED_END)).toBe(idle);
    });

    it("SET_RATE → stays idle", () => {
      expect(reduce(idle, setRate(4))).toBe(idle);
    });
  });

  // ─── playing ────────────────────────────────────────────
  describe("playing state", () => {
    it("TOGGLE → paused(pos, rate)", () => {
      expect(reduce(playing4, TOGGLE, 3000)).toEqual(paused(3000, 4));
    });

    it("PLAY_FORWARD cycles rate: 1→2→4→8→1", () => {
      expect(reduce(playing1, PLAY_FWD)).toEqual(playing2);
      expect(reduce(playing2, PLAY_FWD)).toEqual(playing4);
      expect(reduce(playing4, PLAY_FWD)).toEqual(playing8);
      expect(reduce(playing8, PLAY_FWD)).toEqual(playing1);
    });

    it("PLAY_BACKWARD_OR_SLOW at rate>1 → playing(prevRate)", () => {
      expect(reduce(playing8, PLAY_BWD)).toEqual(playing4);
      expect(reduce(playing4, PLAY_BWD)).toEqual(playing2);
      expect(reduce(playing2, PLAY_BWD)).toEqual(playing1);
    });

    it("PLAY_BACKWARD_OR_SLOW at rate=1 → paused(pos-1s, 1)", () => {
      const result = reduce(playing1, PLAY_BWD, 5000);
      expect(result).toEqual(paused(4000, 1));
    });

    it("PLAY_BACKWARD_OR_SLOW at rate=1, playhead near 0 → paused(0, 1)", () => {
      const result = reduce(playing1, PLAY_BWD, 500);
      expect(result).toEqual(paused(0, 1));
    });

    it("HARD_PAUSE → paused(pos, 1)", () => {
      expect(reduce(playing4, HARD_PAUSE, 2000)).toEqual(paused(2000, 1));
    });

    it("SEEK → seeking(pos→to, resume=playing r)", () => {
      expect(reduce(playing4, seekEv(7000), 3000)).toEqual(
        seeking(3000, 7000, playing4),
      );
    });

    it("SEEK_DONE → stays playing (n/a)", () => {
      expect(reduce(playing4, SEEK_DONE)).toBe(playing4);
    });

    it("REACHED_END → paused(end, rate)", () => {
      expect(reduce(playing4, REACHED_END, 9900, 10000)).toEqual(
        paused(10000, 4),
      );
    });

    it("SET_RATE → playing(newRate)", () => {
      expect(reduce(playing1, setRate(8))).toEqual(playing8);
    });
  });

  // ─── paused ─────────────────────────────────────────────
  describe("paused state", () => {
    const p = paused(3000, 4);

    it("TOGGLE → playing(resumeRate) — preserves rate", () => {
      expect(reduce(p, TOGGLE)).toEqual({ kind: "playing", rate: 4 });
    });

    it("PLAY_FORWARD → playing(1)", () => {
      expect(reduce(p, PLAY_FWD)).toEqual(playing1);
    });

    it("PLAY_BACKWARD_OR_SLOW → stays paused (jog handled externally)", () => {
      expect(reduce(p, PLAY_BWD)).toBe(p);
    });

    it("HARD_PAUSE → stays paused", () => {
      expect(reduce(p, HARD_PAUSE)).toBe(p);
    });

    it("SEEK → seeking(pos→to, resume=paused(to, resumeRate))", () => {
      const result = reduce(p, seekEv(7000));
      expect(result).toEqual(
        seeking(3000, 7000, paused(7000, 4)),
      );
    });

    it("SEEK_DONE → stays paused (n/a)", () => {
      expect(reduce(p, SEEK_DONE)).toBe(p);
    });

    it("REACHED_END → stays paused", () => {
      expect(reduce(p, REACHED_END)).toBe(p);
    });

    it("SET_RATE → paused(pos, newRate)", () => {
      expect(reduce(p, setRate(2))).toEqual(paused(3000, 2));
    });
  });

  // ─── seeking ────────────────────────────────────────────
  describe("seeking state", () => {
    const s = seeking(1000, 5000, playing4);

    it("TOGGLE → stays seeking", () => {
      expect(reduce(s, TOGGLE)).toBe(s);
    });

    it("PLAY_FORWARD → stays seeking", () => {
      expect(reduce(s, PLAY_FWD)).toBe(s);
    });

    it("PLAY_BACKWARD_OR_SLOW → stays seeking", () => {
      expect(reduce(s, PLAY_BWD)).toBe(s);
    });

    it("HARD_PAUSE → stays seeking", () => {
      expect(reduce(s, HARD_PAUSE)).toBe(s);
    });

    it("SEEK coalesces: keep from, update to", () => {
      const result = reduce(s, seekEv(8000));
      expect(result).toEqual(seeking(1000, 8000, playing4));
    });

    it("SEEK_DONE → resume state (playing)", () => {
      const result = reduce(s, SEEK_DONE);
      expect(result).toEqual(playing4);
    });

    it("SEEK_DONE with paused resume → paused with updated pausedAtMs=to", () => {
      const sPaused = seeking(1000, 5000, paused(1000, 2));
      const result = reduce(sPaused, SEEK_DONE);
      expect(result).toEqual(paused(5000, 2));
    });

    it("REACHED_END → paused(end, 1)", () => {
      const result = reduce(s, REACHED_END, 9999, 10000);
      expect(result).toEqual(paused(10000, 1));
    });

    it("SET_RATE → stays seeking", () => {
      expect(reduce(s, setRate(8))).toBe(s);
    });
  });

  // ─── edge cases ─────────────────────────────────────────
  describe("edge cases", () => {
    it("rate-resume after pause: pause→play returns to last rate", () => {
      // Start at 4×, pause, resume → should be 4×
      let pb: Playback = playing4;
      pb = reduce(pb, TOGGLE, 5000); // → paused(5000, 4)
      expect(pb).toEqual(paused(5000, 4));
      pb = reduce(pb, TOGGLE); // → playing(4)
      expect(pb).toEqual(playing4);
    });

    it("REACHED_END from playing 4× → paused(end, 4)", () => {
      const result = reduce(playing4, REACHED_END, 9900, 10000);
      expect(result).toEqual(paused(10000, 4));
    });

    it("coalesce-during-seek: multiple seeks keep original from", () => {
      let pb: Playback = seeking(1000, 3000, playing1);
      pb = reduce(pb, seekEv(5000));
      expect(pb).toEqual(seeking(1000, 5000, playing1));
      pb = reduce(pb, seekEv(7000));
      expect(pb).toEqual(seeking(1000, 7000, playing1));
    });

    it("idle → SEEK → SEEK_DONE → returns to idle", () => {
      let pb: Playback = idle;
      pb = reduce(pb, seekEv(3000));
      expect(pb.kind).toBe("seeking");
      pb = reduce(pb, SEEK_DONE);
      expect(pb).toEqual(idle);
    });
  });
});
