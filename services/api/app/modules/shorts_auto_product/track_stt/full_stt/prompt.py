"""Prompt construction for the full-STT product explainer picker.

No slot structure. No HOOK/INTRO/DETAIL/CTA. The LLM decides how many
segments to pick and which ones — we only constrain the output shape
(chronological, 3-8 segments, no timestamp hallucination).

Imports only: full_stt/types.FullSttScene (no other track_stt deps).
"""

from __future__ import annotations

from app.modules.shorts_auto_product.track_stt.full_stt.types import FullSttScene


PROMPT_VERSION = "v3"

_SYSTEM_PROMPT = (
    "You are a video editor. The transcript below is split into consecutive "
    "multi-scene chunks (each entry merges several adjacent scenes). Select "
    "chunk(s) that explain the product clearly to someone who was not present "
    "at the live stream.\n\n"
    "Each transcript entry is context for a source range. The final rendered "
    "short will be assembled from original scenes inside the selected chunk(s), "
    "so pick the chunk(s) with the best product story even if a full chunk is "
    "longer than the target duration.\n\n"
    "Guidelines:\n"
    "- Select 1-2 chunks. Prefer 1 if it already covers the product story well.\n"
    "- Each chunk must explain, demonstrate, or describe the product "
    "(what it does, who it is for, why it matters)\n"
    "- If picking 2, they must cover distinct story beats — no redundancy\n"
    "- Prefer chunks that are self-contained over heavily context-dependent ones\n"
    "- Avoid time-sensitive language (\"today only\", \"limited stock\", \"right now\") "
    "— this clip will be watched weeks or months after the live stream\n"
    "- Chunks must be in chronological order\n\n"
    "Return the segment_index of each chosen chunk and a short rationale. "
    "Chunks must be in chronological order."
)


# ── Multi-short (shared planner) prompt ──────────────────────────────
# Parallel to the single-short prompt above. The shared planner asks for
# N meaningfully-different shorts in ONE call. The legacy single-short
# prompt is left byte-stable so the flag-off path is an exact rollback.
MULTI_PROMPT_VERSION = "v4"

_MULTI_SYSTEM_PROMPT = (
    "You are a video editor. The transcript below is split into consecutive "
    "multi-scene chunks (each entry merges several adjacent scenes). Produce "
    "several distinct short video edits that each explain the product clearly "
    "to someone who was not present at the live stream.\n\n"
    "Each transcript entry is context for a source range. The final rendered "
    "short will be assembled from original scenes inside the selected chunk(s), "
    "so pick the chunk(s) with the best product story even if a full chunk is "
    "longer than the target duration.\n\n"
    "Guidelines:\n"
    "- Produce exactly the requested number of shorts\n"
    "- Each short selects 1-2 chunks. Prefer 1 if a single chunk already covers "
    "the product story well.\n"
    "- Every chunk must explain, demonstrate, or describe the product "
    "(what it does, who it is for, why it matters)\n"
    "- Within a short, avoid redundancy and keep chunks in chronological order\n"
    "- Make the shorts MEANINGFULLY DIFFERENT from one another: feature distinct "
    "moments of the video and vary the aspect of the product emphasized. "
    "Do not return the same selection twice.\n"
    "- Avoid time-sensitive language (\"today only\", \"limited stock\", "
    "\"right now\") — these clips will be watched weeks or months later\n\n"
    "For each short return: the segment_index of each chosen chunk with a short "
    "per-segment rationale, a global_rationale for the short, and a "
    "differentiation_note saying how this short differs from the others. "
    "Chunks within each short must be in chronological order."
)


def _ms_to_mmss(ms: int) -> str:
    total_s = ms // 1000
    return f"{total_s // 60:02d}:{total_s % 60:02d}"


def group_consecutive_scenes(
    scenes: list[FullSttScene],
    group_size: int = 15,
) -> list[list[FullSttScene]]:
    """Group every ``group_size`` consecutive scenes.

    Returns one-scene groups when ``group_size <= 1``. The picker uses these
    groups to map LLM-selected prompt chunks back to original renderable scenes.
    """
    if not scenes:
        return []
    if group_size <= 1:
        return [[scene] for scene in scenes]
    return [scenes[i : i + group_size] for i in range(0, len(scenes), group_size)]


def merge_consecutive_scenes(
    scenes: list[FullSttScene],
    group_size: int = 15,
) -> list[FullSttScene]:
    """Merge every ``group_size`` consecutive scenes into one combined scene.

    Concatenates transcript text, spans time range from the first scene's
    ``start_ms`` to the last scene's ``end_ms``, and takes the first
    scene's ``scene_id``. The last group may contain fewer than
    ``group_size`` scenes.

    Returns the input unchanged when ``group_size <= 1``.
    """
    merged: list[FullSttScene] = []
    for group in group_consecutive_scenes(scenes, group_size=group_size):
        combined_text = " ".join(s.text for s in group if s.text).strip()
        merged.append(
            FullSttScene(
                scene_id=group[0].scene_id,
                start_ms=group[0].start_ms,
                end_ms=group[-1].end_ms,
                text=combined_text,
            )
        )
    return merged


def select_scenes_for_prompt(
    scenes: list[FullSttScene],
    max_scenes: int,
) -> list[FullSttScene]:
    """Cap scenes to max_scenes with temporal coverage across thirds.

    Divides the source into 3 equal thirds by list position and samples up
    to max_scenes // 3 scenes from each third (remainder goes to the last
    third). Evenly-spaced sampling within each third preserves the rhythm
    of the source while fitting the budget.

    Returns the input unchanged when len(scenes) <= max_scenes.
    """
    sorted_scenes = sorted(scenes, key=lambda s: s.start_ms)

    if len(sorted_scenes) <= max_scenes:
        return sorted_scenes

    n = len(sorted_scenes)
    per_third = max_scenes // 3
    extra = max_scenes - per_third * 3  # distribute remainder to last third

    third = n // 3
    first = sorted_scenes[:third]
    middle = sorted_scenes[third : 2 * third]
    last = sorted_scenes[2 * third :]

    def _evenly_sample(src: list[FullSttScene], count: int) -> list[FullSttScene]:
        if not src or count <= 0:
            return []
        if len(src) <= count:
            return list(src)
        step = len(src) / count
        return [src[int(i * step)] for i in range(count)]

    return (
        _evenly_sample(first, per_third)
        + _evenly_sample(middle, per_third)
        + _evenly_sample(last, per_third + extra)
    )


def build_user_prompt(
    *,
    scenes: list[FullSttScene],
    target_duration_ms: int,
    llm_label: str,
    spoken_aliases: list[str],
) -> str:
    """Format the user-turn prompt from a pre-capped, chronologically-sorted
    scene list.

    Callers are responsible for capping and sorting (see
    ``select_scenes_for_prompt``). This function is pure formatting.
    """
    target_s = target_duration_ms // 1000
    total_ms = scenes[-1].end_ms if scenes else 0

    clean_aliases = [a for a in (spoken_aliases or []) if a and a != llm_label]
    alias_str = ", ".join(clean_aliases) if clean_aliases else "(no aliases)"

    lines = [
        f"Product: {llm_label} (also called: {alias_str})",
        f"Target duration: {target_s}s",
        f"Source: {_ms_to_mmss(total_ms)}",
        "",
        f"Transcript ({len(scenes)} scenes, chronological, 0-indexed):",
    ]
    for idx, scene in enumerate(scenes):
        start_str = _ms_to_mmss(scene.start_ms)
        end_str = _ms_to_mmss(scene.end_ms)
        text = scene.text.replace('"', "'")
        lines.append(f'[{idx}] {start_str}-{end_str} "{text}"')

    return "\n".join(lines)


def build_multi_user_prompt(
    *,
    scenes: list[FullSttScene],
    target_duration_ms: int,
    llm_label: str,
    spoken_aliases: list[str],
    n: int,
) -> str:
    """User-turn prompt for the shared planner: ask for ``n`` distinct shorts.

    Reuses ``build_user_prompt`` for the product header + transcript block
    (single source of truth for the scene formatting) and prepends the
    N-shorts instruction. Callers cap + sort scenes upstream.
    """
    target_s = target_duration_ms // 1000
    header = (
        f"Produce exactly {n} shorts, each approximately {target_s}s, that are "
        f"meaningfully different from one another.\n"
    )
    base = build_user_prompt(
        scenes=scenes,
        target_duration_ms=target_duration_ms,
        llm_label=llm_label,
        spoken_aliases=spoken_aliases,
    )
    return header + "\n" + base
