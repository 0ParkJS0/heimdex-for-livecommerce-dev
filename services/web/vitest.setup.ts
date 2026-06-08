import "@testing-library/jest-dom/vitest";

// jsdom does not implement Element.prototype.scrollIntoView. Components that
// scroll an active element into view (e.g. the scene list's auto-scroll on the
// deep-linked scene) call it during effects and would otherwise throw under the
// test environment. No-op it globally so tests exercise the surrounding logic.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}
