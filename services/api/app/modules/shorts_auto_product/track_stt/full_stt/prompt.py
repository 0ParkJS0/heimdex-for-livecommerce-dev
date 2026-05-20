"""Prompt construction for the full-STT product explainer picker.

No slot structure. No HOOK/INTRO/DETAIL/CTA. The LLM decides how many
segments to pick and which ones — we only constrain the output shape
(chronological, 3-8 segments, no timestamp hallucination).

Imports only: full_stt/types.FullSttScene (no other track_stt deps).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.shorts_auto_product.track_stt.full_stt.types import FullSttScene


PROMPT_VERSION = "v2"

_SYSTEM_PROMPT = (
    "You are a video editor. Given a live commerce video transcript, select "
    "segments that together explain the product clearly to someone who was not "
    "present at the live stream.\n\n"
    "Guidelines:\n"
    "- Select 3-8 segments whose combined length is approximately the target duration\n"
    "- Each segment must explain, demonstrate, or describe the product "
    "(what it does, who it is for, why it matters)\n"
    "- Avoid redundancy — do not pick multiple segments that say the same thing\n"
    "- Prefer clear, self-contained segments over heavily context-dependent ones\n"
    "- Avoid time-sensitive language (\"today only\", \"limited stock\", \"right now\") "
    "— this clip will be watched weeks or months after the live stream\n"
    "- Segments must be in chronological order\n\n"
    "Return the segment_index of each chosen scene and a short rationale. "
    "Segments must be in chronological order."
)


def _ms_to_mmss(ms: int) -> str:
    total_s = ms // 1000
    return f"{total_s // 60:02d}:{total_s % 60:02d}"


def select_scenes_for_prompt(
    scenes: list["FullSttScene"],
    max_scenes: int,
) -> list["FullSttScene"]:
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

    def _evenly_sample(src: list["FullSttScene"], count: int) -> list["FullSttScene"]:
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
    scenes: list["FullSttScene"],
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
    total_s = total_ms // 1000

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
