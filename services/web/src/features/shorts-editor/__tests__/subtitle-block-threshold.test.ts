import { describe, it, expect } from "vitest";
import {
  MIN_BLOCK_WIDTH_PX_FOR_TEXT,
  shouldShowSubtitleBlockText,
} from "../components/SubtitleBlock";

// Boundary unit test for the timeline subtitle-block text-hide rule.
// Operator request 2026-05-26: raise the threshold from 20 → 45 px so
// zoom-out doesn't leave noisy 1-2 character truncated previews. Lock
// the boundary so a casual "let's go back to 20" can't slip in
// unnoticed.
describe("shouldShowSubtitleBlockText", () => {
  it("constant equals the operator-locked 45 px threshold", () => {
    expect(MIN_BLOCK_WIDTH_PX_FOR_TEXT).toBe(45);
  });

  it("returns true at and above the threshold", () => {
    expect(shouldShowSubtitleBlockText(45)).toBe(true);
    expect(shouldShowSubtitleBlockText(46)).toBe(true);
    expect(shouldShowSubtitleBlockText(200)).toBe(true);
  });

  it("returns false just below the threshold (no 1-2 char preview)", () => {
    expect(shouldShowSubtitleBlockText(44)).toBe(false);
    expect(shouldShowSubtitleBlockText(20)).toBe(false); // pre-2026-05-26 floor
    expect(shouldShowSubtitleBlockText(0)).toBe(false);
  });
});
