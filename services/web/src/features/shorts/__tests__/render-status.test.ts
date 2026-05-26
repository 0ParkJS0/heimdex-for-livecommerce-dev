/**
 * Render-status predicate table — pins the dot-3 menu's gating logic.
 *
 * The Download menu item is only meaningful for completed renders
 * (we have a signed URL); the status pill picks between three
 * branches based on the queued/rendering/failed/completed split. Lock
 * the truth table so a future refactor (e.g. adding a "paused" status)
 * has to touch the predicates explicitly.
 */

import { describe, it, expect } from "vitest";

import {
  isCompletedRender,
  isFailedRender,
  isRenderingRender,
} from "../lib/render-status";

const cases = [
  {
    label: "saved row",
    item: { type: "saved" as const },
    rendering: false,
    completed: false,
    failed: false,
  },
  {
    label: "render queued",
    item: { type: "render" as const, status: "queued" },
    rendering: true,
    completed: false,
    failed: false,
  },
  {
    label: "render rendering",
    item: { type: "render" as const, status: "rendering" },
    rendering: true,
    completed: false,
    failed: false,
  },
  {
    label: "render completed",
    item: { type: "render" as const, status: "completed" },
    rendering: false,
    completed: true,
    failed: false,
  },
  {
    label: "render failed",
    item: { type: "render" as const, status: "failed" },
    rendering: false,
    completed: false,
    failed: true,
  },
  {
    label: "render with missing status",
    item: { type: "render" as const },
    rendering: false,
    completed: false,
    failed: false,
  },
  {
    label: "render with unknown status",
    item: { type: "render" as const, status: "paused" },
    rendering: false,
    completed: false,
    failed: false,
  },
];

describe("render-status predicates", () => {
  it.each(cases)(
    "$label — rendering=$rendering completed=$completed failed=$failed",
    ({ item, rendering, completed, failed }) => {
      expect(isRenderingRender(item)).toBe(rendering);
      expect(isCompletedRender(item)).toBe(completed);
      expect(isFailedRender(item)).toBe(failed);
    },
  );
});
