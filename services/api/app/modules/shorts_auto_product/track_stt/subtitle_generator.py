"""Backend port of the FE ``generateSubtitlesFromTranscript`` chunker.

The auto-shorts product mode runs entirely server-side — the
operator's first viewing of a rendered short is the MP4 the
shorts-render-worker produces. If we don't burn subtitles into that
MP4 at render time, every operator has to manually open the
EditClipsPage and re-export to get burnt-in subtitles. The first-view
UX (``/export/shorts``) then ships subtitle-free MP4s, which is what
operators saw on staging 2026-05-06.

Same chunking heuristic as ``services/web/src/features/shorts-editor/
hooks/useEditorState.ts::chunkSubtitleText``:

* 25-char target per row (≈ 5-7 Korean eojeol; reads in 1-2s at
  livecommerce pace).
* Two-pass split — sentence boundaries first, then Korean clause
  boundaries (conjunctive endings + commas) within oversize sentences;
  eojeol-greedy fallback for runaway clauses without internal
  boundaries.
* Distribution timing — chunks fan out across the source clip's
  timeline window with an 800ms minimum per-chunk duration.

Pure functions. No I/O. Trivially testable.
"""

from __future__ import annotations

import re

# Sentence-ending patterns (Korean + Latin) — primary split.
# Python's ``re`` requires fixed-width lookbehinds, so we split into
# two alternatives instead of the FE's variable-width form.
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[.!?。])\s+|(?<=[요다죠음네까게세지])\s+(?=[가-힣A-Za-z0-9])"
)

# Korean clause-boundary patterns — secondary split for finer chunks.
# Conjunctive endings ("는데", "면서요", "이기 때문에", etc.) and
# connective particles mark natural pause points.
_CLAUSE_SPLIT_RE = re.compile(
    r"(?<=,)\s+|(?<=[는면서고지만니까데서야면])\s+(?=[가-힣])"
)

# Whitespace runs.
_WHITESPACE_RE = re.compile(r"\s+")

_MAX_SUBTITLE_CHARS = 25
_MIN_CHUNK_DURATION_MS = 800


# ``SPEAKER_00 [1:23]: text`` lines (timestamp optional). Mirror of
# the FE ``LINE_PATTERN`` in ``services/web/src/lib/speaker-transcript.ts``.
_SPEAKER_LINE_RE = re.compile(r"^(\S+?)(?:\s+\[([^\]]+)\])?\s*:\s*(.+)$")
_TIMESTAMP_RE = re.compile(r"^(\d+):(\d{1,2})$")


def parse_timestamp_ms(raw: str | None) -> int | None:
    """Parse ``"mm:ss"`` (or ``"mmm:ss"`` for hour-plus) → milliseconds.

    Returns ``None`` when the input doesn't match the format. The FE
    uses the same format on speaker_transcript turn markers, so backend
    + frontend agree on what counts as a valid timestamp.
    """
    if not raw:
        return None
    m = _TIMESTAMP_RE.match(raw.strip())
    if not m:
        return None
    minutes = int(m.group(1))
    seconds = int(m.group(2))
    return (minutes * 60 + seconds) * 1000


def parse_speaker_transcript(
    transcript: str | None,
) -> list[tuple[str, int | None]]:
    """Parse a speaker_transcript blob into ``(text, timestamp_ms)`` tuples.

    Mirrors :func:`parseSpeakerTranscript` in
    ``services/web/src/lib/speaker-transcript.ts`` so backend + FE
    agree on segmentation. Returns ``[]`` when the input is empty,
    whitespace-only, or doesn't have any parseable lines.

    Lines without a timestamp marker contribute their text with
    ``timestamp_ms=None`` — the caller falls back to uniform
    distribution for those turns.
    """
    if not transcript or not transcript.strip():
        return []
    out: list[tuple[str, int | None]] = []
    for line in transcript.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        m = _SPEAKER_LINE_RE.match(stripped)
        if not m:
            # Continuation line — append to the previous turn's text.
            if out:
                prev_text, prev_ts = out[-1]
                out[-1] = (f"{prev_text} {stripped}", prev_ts)
            continue
        timestamp = parse_timestamp_ms(m.group(2))
        text = m.group(3).strip()
        if not text:
            continue
        out.append((text, timestamp))
    return out


def chunk_subtitle_text(text: str) -> list[str]:
    """Two-pass chunker matching the FE behavior.

    Returns ``[]`` for empty / whitespace-only input. Otherwise
    returns 1+ chunks, each ≤ ``_MAX_SUBTITLE_CHARS`` long.
    """
    trimmed = (text or "").strip()
    if not trimmed:
        return []
    if len(trimmed) <= _MAX_SUBTITLE_CHARS:
        return [trimmed]

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(trimmed) if s.strip()]
    chunks: list[str] = []

    for sentence in sentences:
        if len(sentence) <= _MAX_SUBTITLE_CHARS:
            chunks.append(sentence)
            continue
        # Pass 2: clause-level split inside an oversize sentence.
        clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(sentence) if c.strip()]
        current = ""
        for clause in clauses:
            if len(clause) > _MAX_SUBTITLE_CHARS:
                # Pass 3: eojeol greedy pack — fall through when a
                # single clause is still too long.
                if current:
                    chunks.append(current)
                    current = ""
                eojeols = clause.split()
                buf = ""
                for e in eojeols:
                    nxt = f"{buf} {e}" if buf else e
                    if len(nxt) > _MAX_SUBTITLE_CHARS:
                        if buf:
                            chunks.append(buf)
                        buf = e
                    else:
                        buf = nxt
                if buf:
                    current = buf
                continue
            candidate = f"{current} {clause}" if current else clause
            if len(candidate) <= _MAX_SUBTITLE_CHARS:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = clause
        if current:
            chunks.append(current)

    return chunks if chunks else [trimmed[:_MAX_SUBTITLE_CHARS]]


def distribute_subtitles_for_clip(
    *,
    transcript: str,
    timeline_start_ms: int,
    clip_duration_ms: int,
) -> list[tuple[int, int, str]]:
    """Generate subtitle (start_ms, end_ms, text) tuples for one clip.

    Args:
        transcript: The clip's underlying transcript text. Empty /
            ``None`` returns ``[]``.
        timeline_start_ms: Where on the FINAL composition timeline
            this clip starts. Subtitle ``start_ms`` and ``end_ms`` are
            timeline-relative.
        clip_duration_ms: How long the clip spans on the timeline.

    Returns:
        List of ``(start_ms, end_ms, text)`` tuples. Empty when the
        transcript yielded no chunks. Each subtitle is bounded inside
        the clip's window and is at least 800ms long; if a uniform
        distribution would produce shorter slices, we cap the chunk
        count to fit.
    """
    if not transcript or clip_duration_ms <= 0:
        return []
    chunks = chunk_subtitle_text(transcript)
    if not chunks:
        return []

    # Cap chunk count so each chunk gets at least the minimum
    # duration. A 3-second clip with 8 chunks would force 375ms each
    # — too fast to read; better to merge into 3-4 chunks of ~800ms.
    max_chunks = max(1, clip_duration_ms // _MIN_CHUNK_DURATION_MS)
    if len(chunks) > max_chunks:
        chunks = _merge_chunks_to_count(chunks, max_chunks)

    chunk_duration_ms = max(
        _MIN_CHUNK_DURATION_MS,
        clip_duration_ms // len(chunks),
    )
    out: list[tuple[int, int, str]] = []
    for i, text in enumerate(chunks):
        start = timeline_start_ms + i * chunk_duration_ms
        end = min(
            start + chunk_duration_ms,
            timeline_start_ms + clip_duration_ms,
        )
        if end <= start:
            continue
        out.append((start, end, text))
    return out


def distribute_subtitles_with_speaker_timing(
    *,
    speaker_transcript: str,
    src_start_ms: int,
    src_end_ms: int,
    timeline_start_ms: int,
) -> list[tuple[int, int, str]]:
    """Time-align subtitles using ``speaker_transcript`` turn timestamps.

    Use this when scenes carry the ``"SPEAKER_00 [mm:ss]: text"``
    formatted transcript — much closer to "subtitles appear when the
    host says the words" than uniform distribution.

    Algorithm:
      1. Parse turns from speaker_transcript.
      2. Filter to turns whose timestamp lies within the clip's
         source window ``[src_start_ms, src_end_ms]``.
      3. For each kept turn, chunk its text and distribute the
         chunks across the time slot bounded by this turn's
         timestamp and the next kept turn's timestamp (or
         ``src_end_ms`` for the final turn).
      4. Convert each subtitle's source-time bounds to timeline-time
         (subtract ``src_start_ms``, add ``timeline_start_ms``).

    Returns ``[]`` when no turns fall inside the source window —
    caller should fall back to uniform distribution.
    """
    clip_duration_ms = src_end_ms - src_start_ms
    if clip_duration_ms <= 0:
        return []
    turns = parse_speaker_transcript(speaker_transcript)
    if not turns:
        return []

    # Keep only turns that have a usable timestamp inside the window.
    kept: list[tuple[int, str]] = []
    for text, ts_ms in turns:
        if ts_ms is None:
            continue
        if ts_ms < src_start_ms or ts_ms >= src_end_ms:
            continue
        kept.append((ts_ms, text))
    if not kept:
        return []

    out: list[tuple[int, int, str]] = []
    for i, (turn_ts, turn_text) in enumerate(kept):
        # Slot ends at the next kept turn's timestamp, or src_end_ms
        # for the final turn.
        next_ts = kept[i + 1][0] if i + 1 < len(kept) else src_end_ms
        slot_duration_ms = max(0, next_ts - turn_ts)
        if slot_duration_ms <= 0:
            continue
        chunks = chunk_subtitle_text(turn_text)
        if not chunks:
            continue
        max_chunks = max(1, slot_duration_ms // _MIN_CHUNK_DURATION_MS)
        if len(chunks) > max_chunks:
            chunks = _merge_chunks_to_count(chunks, max_chunks)
        chunk_duration_ms = max(
            _MIN_CHUNK_DURATION_MS,
            slot_duration_ms // len(chunks),
        )
        for j, text in enumerate(chunks):
            src_chunk_start = turn_ts + j * chunk_duration_ms
            src_chunk_end = min(
                src_chunk_start + chunk_duration_ms,
                next_ts,
            )
            if src_chunk_end <= src_chunk_start:
                continue
            timeline_start = (src_chunk_start - src_start_ms) + timeline_start_ms
            timeline_end = (src_chunk_end - src_start_ms) + timeline_start_ms
            if timeline_end <= timeline_start:
                continue
            out.append((timeline_start, timeline_end, text))
    return out


def _merge_chunks_to_count(chunks: list[str], target_count: int) -> list[str]:
    """Greedy merge adjacent chunks until len(chunks) == target_count.

    Used when uniform distribution would compress per-chunk duration
    below the readable minimum. Merging neighbors preserves the
    chunker's reading-rhythm choices better than dropping every
    other chunk.
    """
    if target_count <= 0 or not chunks:
        return chunks
    merged = list(chunks)
    while len(merged) > target_count:
        # Find the shortest adjacent pair (sum of lengths) and merge.
        best_i = 0
        best_len = len(merged[0]) + len(merged[1]) if len(merged) >= 2 else 0
        for i in range(1, len(merged) - 1):
            pair_len = len(merged[i]) + len(merged[i + 1])
            if pair_len < best_len:
                best_len = pair_len
                best_i = i
        merged[best_i] = f"{merged[best_i]} {merged[best_i + 1]}"
        del merged[best_i + 1]
    return merged
