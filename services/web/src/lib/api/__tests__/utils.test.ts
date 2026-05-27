import { describe, expect, it } from "vitest";

import { formatErrorDetail } from "@/lib/api/utils";

const FALLBACK = "fallback message";

describe("formatErrorDetail", () => {
  // The whole point of B3: a FastAPI 422 array `detail` must become a
  // readable string instead of "[object Object],[object Object]".
  describe("success transforms", () => {
    it("passes a plain string through", () => {
      expect(formatErrorDetail("boom", FALLBACK)).toBe("boom");
    });

    it("joins a FastAPI 422 array on each entry's msg", () => {
      const detail = [
        { type: "missing", loc: ["body", "title"], msg: "Field required" },
        { type: "string_type", loc: ["body", "length"], msg: "Input should be a valid string" },
      ];
      expect(formatErrorDetail(detail, FALLBACK)).toBe(
        "Field required, Input should be a valid string",
      );
    });

    it("falls back to a loc-anchored label when an entry has no usable msg", () => {
      const detail = [{ type: "missing", loc: ["body", "title"] }];
      expect(formatErrorDetail(detail, FALLBACK)).toBe(
        "validation error at body.title",
      );
    });

    it("does NOT interpolate a non-string msg into the loc label (the ${msg} bug)", () => {
      // msg is a number here — must not render "0 at ..." / "undefined at ..."
      const detail = [{ loc: ["body", "x"], msg: 0 }];
      const out = formatErrorDetail(detail, FALLBACK);
      expect(out).toBe("validation error at body.x");
      expect(out).not.toContain("undefined");
      expect(out).not.toContain("0 at");
    });

    it("handles a string array", () => {
      expect(formatErrorDetail(["a", "b"], FALLBACK)).toBe("a, b");
    });

    it("JSON-stringifies an array entry with neither msg nor loc", () => {
      expect(formatErrorDetail([{ foo: "bar" }], FALLBACK)).toBe(
        JSON.stringify({ foo: "bar" }),
      );
    });

    it("JSON-stringifies a bare object detail", () => {
      expect(formatErrorDetail({ code: "x" }, FALLBACK)).toBe(
        JSON.stringify({ code: "x" }),
      );
    });

    it("stringifies a scalar (number) detail", () => {
      expect(formatErrorDetail(422, FALLBACK)).toBe("422");
    });
  });

  describe("fallback paths", () => {
    it("returns fallback for null", () => {
      expect(formatErrorDetail(null, FALLBACK)).toBe(FALLBACK);
    });

    it("returns fallback for undefined", () => {
      expect(formatErrorDetail(undefined, FALLBACK)).toBe(FALLBACK);
    });

    it("returns fallback for an empty string", () => {
      expect(formatErrorDetail("", FALLBACK)).toBe(FALLBACK);
    });

    it("returns fallback for an empty array", () => {
      expect(formatErrorDetail([], FALLBACK)).toBe(FALLBACK);
    });
  });
});
