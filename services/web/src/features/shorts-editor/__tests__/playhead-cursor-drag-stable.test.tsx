/**
 * PlayheadCursor drag stability — figma issue 2026-05-26.
 *
 * Pins the fix where dragging the playhead used to die after the first
 * mouse move. Root cause: parent timeline rebuilt ``onSeek`` on every
 * dispatched seek (snap-points array → handleSeekWithSnap useCallback →
 * onSeek prop new identity), which invalidated PlayheadCursor's
 * onPointerMove useCallback identity, which triggered the cleanup
 * useEffect to remove the document pointermove listener. onPointerDown
 * only re-attaches on mouse-down, so the rest of the drag was dead.
 *
 * The fix routes onSeek + zoom through useRef so onPointerMove keeps a
 * stable identity for the lifetime of the component. This test fires a
 * pointerdown, re-renders the wrapper with a brand-new onSeek function
 * reference, then fires a pointermove and asserts the latest onSeek
 * (the one that was current at move-time) is actually invoked. Before
 * the fix the document listener had been torn down so neither the old
 * nor the new onSeek fired.
 */

import { describe, it, expect, beforeAll } from "vitest";
import { render, fireEvent } from "@testing-library/react";

import { PlayheadCursor } from "@/lib/timeline/PlayheadCursor";

// jsdom doesn't implement the Pointer Capture API. PlayheadCursor calls
// setPointerCapture / releasePointerCapture during drag, so stub them
// before any render. Otherwise the pointerdown listener throws and the
// test would fail for the wrong reason.
beforeAll(() => {
  Element.prototype.setPointerCapture = function () {};
  Element.prototype.releasePointerCapture = function () {};
});

function Harness({
  onSeekVersion,
  recordSeek,
}: {
  onSeekVersion: number;
  recordSeek: (version: number, ms: number) => void;
}) {
  // A brand-new function identity every render keyed on onSeekVersion,
  // mirroring the production cascade where the parent rebuilds onSeek
  // every dispatch.
  const onSeek = (ms: number) => recordSeek(onSeekVersion, ms);
  return (
    <PlayheadCursor playheadMs={0} zoom={1} height={100} onSeek={onSeek} />
  );
}

function firePointerDown(container: HTMLElement, clientX: number) {
  // The drag handle is the inner cursor-grab div; targeting the
  // PlayheadCursor wrapper itself doesn't work because the wrapper has
  // pointer-events-none on the outer layout.
  const handle = container.querySelector(".cursor-grab");
  expect(handle).toBeTruthy();
  fireEvent.pointerDown(handle!, {
    clientX,
    pointerId: 1,
    bubbles: true,
  });
}

describe("PlayheadCursor — drag survives parent onSeek identity changes", () => {
  it("fires the latest onSeek on pointermove even after the parent re-rendered with a new onSeek reference", () => {
    const seekCalls: Array<{ version: number; ms: number }> = [];
    const recordSeek = (version: number, ms: number) =>
      seekCalls.push({ version, ms });

    const { container, rerender } = render(
      <Harness onSeekVersion={1} recordSeek={recordSeek} />,
    );

    // 1) Start the drag at clientX=100. This wires the document
    //    pointermove listener via onPointerDown.
    firePointerDown(container, 100);

    // 2) Simulate the production cascade: parent re-renders with a new
    //    onSeek identity. Before the fix this tore the listener down.
    rerender(<Harness onSeekVersion={2} recordSeek={recordSeek} />);

    // 3) Fire a pointermove on the document. The fixed component must
    //    still have the listener attached, AND it must call the latest
    //    onSeek (version=2) because the ref captures the freshest one.
    fireEvent(
      document,
      new PointerEvent("pointermove", {
        clientX: 250,
        bubbles: true,
        pointerId: 1,
      }),
    );

    expect(seekCalls.length).toBeGreaterThan(0);
    expect(seekCalls[seekCalls.length - 1]).toMatchObject({ version: 2 });

    // 4) Fire one more move so the regression is clear: a drag that
    //    crosses multiple frames must keep firing onSeek.
    fireEvent(
      document,
      new PointerEvent("pointermove", {
        clientX: 400,
        bubbles: true,
        pointerId: 1,
      }),
    );
    expect(seekCalls.length).toBeGreaterThanOrEqual(2);
  });
});
