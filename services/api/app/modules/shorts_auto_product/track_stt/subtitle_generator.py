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
