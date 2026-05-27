"use client";

// Keyboard shortcut layer for the editor (L3).
//
// Centralizes every editor-wide hotkey in one place so the dispatch
// path is searchable + testable. Earlier the handlers lived inline in
// ShortsEditorPage as a 30-line useEffect; growing the keymap (J/K/L,
// I/O, S, etc.) made that block harder to scan. The hook owns:
//
//   * Single document-level keydown listener (no per-shortcut
//     subscription churn).
//   * Input-focus guard so typing in <input>/<textarea>/<select> never
//     swallows characters.
//   * "useEvent" ref pattern for every callback the listener calls —
//     dispatching an action re-renders the parent, which re-renders us,
//     which gives us a new callback identity. Without the refs, the
//     listener would either capture stale callbacks or churn its
//     subscription on every render.
//
// I/O (in/out points) and S (split) are wired in L4 + L5 respectively —
// reserved shortcut slots, not implemented here.

import { useEffect, useRef } from "react";

import type { EditorState, PlaybackEvent } from "../lib/types";

export interface EditorKeyboardOptions {
  state: EditorState;
  setPlayhead: (ms: number) => void;
  dispatchPlaybackEvent: (event: PlaybackEvent) => void;
  selectClip: (index: number | null) => void;
  selectOverlay: (id: string | null) => void;
  selectSubtitle: (index: number | null) => void;
  removeClip: (index: number) => void;
  removeOverlay: (id: string) => void;
  removeSubtitle: (index: number) => void;
  setInPoint: (ms: number | null) => void;
  setOutPoint: (ms: number | null) => void;
  splitAtPlayhead: () => void;
  setRazorMode: (active: boolean) => void;
}

// Frame stepping (L4 / T2). 30 fps is the project standard — short-form
// vertical video on most platforms. Arrow keys move the playhead by
// one frame; Shift+arrow jumps by 10 frames (≈ 1/3 sec) for faster
// frame-by-frame scrubbing without leaving the keyboard.
const FPS = 30;
const FRAME_MS = 1000 / FPS;
const FRAME_STEP_FAST_FRAMES = 10;

export function useEditorKeyboard(opts: EditorKeyboardOptions) {
  // Mirror everything into refs so the listener sees the latest state
  // without re-subscribing. Without this the keyup handler captures
  // whatever `state.playback` was at first mount and never updates.
  const optsRef = useRef(opts);
  useEffect(() => {
    optsRef.current = opts;
  });

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ignore when the user is typing in an editable surface. <select>
      // is included so the operator can use arrow keys inside a dropdown
      // without seeking the playhead.
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      // Modifier keys (Cmd/Ctrl) reserved for OS-level shortcuts — never
      // trigger editor actions. Shift is OK (e.g. Shift+End ranges).
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const {
        state,
        setPlayhead,
        dispatchPlaybackEvent,
        selectClip,
        selectOverlay,
        selectSubtitle,
        removeClip,
        removeOverlay,
        removeSubtitle,
        setInPoint,
        setOutPoint,
        splitAtPlayhead,
        setRazorMode,
      } = optsRef.current;

      const pb = state.playback;

      switch (e.key) {
        case " ":
        case "Spacebar": {
          e.preventDefault();
          dispatchPlaybackEvent({ kind: "TOGGLE" });
          return;
        }

        // ── J/K/L NLE jog/shuttle ─────────────────────────────────
        case "j":
        case "J": {
          e.preventDefault();
          dispatchPlaybackEvent({ kind: "PLAY_BACKWARD_OR_SLOW" });
          // J at idle or playing(1) jogs -1s — the state machine
          // stays in its current state, so we also move the playhead.
          if (pb.kind === "idle" || (pb.kind === "paused")) {
            setPlayhead(Math.max(0, state.playheadMs - 1000));
          }
          return;
        }

        case "k":
        case "K": {
          e.preventDefault();
          dispatchPlaybackEvent({ kind: "HARD_PAUSE" });
          return;
        }

        case "l":
        case "L": {
          e.preventDefault();
          dispatchPlaybackEvent({ kind: "PLAY_FORWARD" });
          return;
        }

        // ── Boundary jumps ────────────────────────────────────────
        case "Home": {
          e.preventDefault();
          dispatchPlaybackEvent({ kind: "SEEK", toMs: 0 });
          // Immediate seek — no waiting for onSeeked for boundary jumps
          setPlayhead(0);
          return;
        }
        case "End": {
          e.preventDefault();
          dispatchPlaybackEvent({ kind: "SEEK", toMs: state.totalDurationMs });
          setPlayhead(state.totalDurationMs);
          return;
        }

        // ── Frame stepping (L4 / T2) ─────────────────────────────
        case "ArrowLeft": {
          e.preventDefault();
          if (pb.kind === "playing") dispatchPlaybackEvent({ kind: "HARD_PAUSE" });
          const step = e.shiftKey ? FRAME_MS * FRAME_STEP_FAST_FRAMES : FRAME_MS;
          const next = Math.max(
            0,
            Math.round((state.playheadMs - step) / FRAME_MS) * FRAME_MS,
          );
          setPlayhead(next);
          return;
        }
        case "ArrowRight": {
          e.preventDefault();
          if (pb.kind === "playing") dispatchPlaybackEvent({ kind: "HARD_PAUSE" });
          const step = e.shiftKey ? FRAME_MS * FRAME_STEP_FAST_FRAMES : FRAME_MS;
          const next = Math.min(
            state.totalDurationMs,
            Math.round((state.playheadMs + step) / FRAME_MS) * FRAME_MS,
          );
          setPlayhead(next);
          return;
        }

        // ── Export range marks (L4 / T2) ─────────────────────────
        // I sets the in-point at the current playhead; O sets the
        // out-point. Shift+I / Shift+O clear the respective mark so
        // operators can wipe a mark without leaving the keyboard.
        case "i":
        case "I": {
          e.preventDefault();
          if (e.shiftKey) setInPoint(null);
          else setInPoint(state.playheadMs);
          return;
        }
        case "o":
        case "O": {
          e.preventDefault();
          if (e.shiftKey) setOutPoint(null);
          else setOutPoint(state.playheadMs);
          return;
        }

        // ── Split / razor (L5 / T5) ──────────────────────────────
        // S toggles razor mode; click-on-block then fires the actual
        // split at the click position and exits razor mode. Pressing
        // S a second time exits razor mode (back to normal cursor).
        case "s":
        case "S": {
          e.preventDefault();
          setRazorMode(!state.razorMode);
          return;
        }

        // ── Selection deletion ─ priority: clip > overlay > subtitle.
        // Mirrors the 2026-05-22 inline-handler logic so we don't lose
        // the operator's mental model when the hook took over.
        case "Delete":
        case "Backspace": {
          if (state.selectedClipIndex != null) {
            removeClip(state.selectedClipIndex);
          } else if (state.selectedOverlayId != null) {
            removeOverlay(state.selectedOverlayId);
          } else if (state.selectedSubtitleIndex != null) {
            removeSubtitle(state.selectedSubtitleIndex);
          }
          return;
        }

        case "Escape": {
          if (state.razorMode) {
            setRazorMode(false);
          } else {
            selectClip(null);
            selectOverlay(null);
            selectSubtitle(null);
          }
          return;
        }

        default:
          return;
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // Listener attached once; refs deliver fresh state on every event.
  }, []);
}
