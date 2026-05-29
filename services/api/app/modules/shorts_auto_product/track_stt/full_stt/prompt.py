"""Prompt construction for the full-STT product mention extractor.

The single-short ``pick`` path extracts EVERY scene range where the
detected product is mentioned (no chunk-pick, no duration packing) via
``_SYSTEM_PROMPT`` + ``build_mention_user_prompt``.

The multi-short ``pick_many`` path is two-stage: stage 1 reuses the exact
same mention extraction above (so "what counts as a mention" lives in ONE
place), and stage 2 groups those already-found regions into N distinct
shorts via ``_MULTI_SYSTEM_PROMPT`` + ``build_grouping_user_prompt``. The
grouping prompt does NOT re-define what a mention is — it only partitions
the regions it is handed.

Imports only: full_stt/types.FullSttScene (no other track_stt deps).
"""

from __future__ import annotations

from app.modules.shorts_auto_product.track_stt.full_stt.types import FullSttScene


PROMPT_VERSION = "v4"

_SYSTEM_PROMPT = (
    "You are analyzing a video transcript to find every moment the product "
    "\"{product_name}\" is discussed. Scenes are listed chronologically with "
    "0-based indices and grouped into chunks (15 consecutive scenes each) so "
    "you can use surrounding context to disambiguate references.\n\n"
    "Your job: return every scene range where \"{product_name}\" — and only "
    "this product — is mentioned, explained, demonstrated, or described. A "
    "'mention' requires the referent to be \"{product_name}\": its name or a "
    "listed alias — including STT-garbled forms that are phonetically close "
    "(e.g. dropped/swapped syllables, split words) — stated explicitly, OR a "
    "pronoun/deictic ('this', 'it') or a feature/use description that nearby "
    "context clearly ties to it. Talk about the product CATEGORY in general, "
    "or about a DIFFERENT same-category product (even in comparison, even "
    "described favorably in detail), does NOT count. When a reference could "
    "plausibly be another product, EXCLUDE it.\n\n"
    "Rules:\n"
    "- Return EVERY qualifying region, but only ones you can tie to "
    "\"{product_name}\"; if it is never mentioned, return an empty list.\n"
    "- A region is a CONSECUTIVE range [start_scene_idx, end_scene_idx], both "
    "bounds inclusive; use the same value for a single scene.\n"
    "- Do NOT merge across a gap: mentions in 5,6,7 and 12 are TWO regions "
    "[5,7] and [12,12].\n"
    "- Chunks are context only; a scene that merely helped resolve a reference "
    "but carries no mention of its own must NOT be in any region.\n"
    "- Regions must be chronological and must not overlap.\n\n"
    "For each region return start_scene_idx, end_scene_idx, and a short "
    "rationale that quotes the actual transcript wording (even if garbled) and "
    "notes why it refers to \"{product_name}\" rather than another product in "
    "the category."
)

def build_mention_system_prompt(llm_label: str) -> str:
    """Fill the {product_name} slots in the mention-extraction system prompt.

    The picker must send the FORMATTED string — sending ``_SYSTEM_PROMPT``
    raw leaves literal ``{product_name}`` in the LLM's instructions and
    silently disables the "only this product" constraint.
    """
    return _SYSTEM_PROMPT.format(product_name=llm_label)


# ── Multi-short grouping prompt (pick_many stage 2) ──────────────────
# Stage 1 already found every product-mention region (reusing the
# single-short extraction above). This prompt ONLY groups those regions
# into N distinct shorts — it must not re-judge what counts as a mention.
# Bumped v4 → v5 when the chunk-pick prompt was replaced by grouping.
MULTI_PROMPT_VERSION = "v5"

_MULTI_SYSTEM_PROMPT = (
    "You are a video editor. Below is a numbered list of transcript regions "
    "that have ALREADY been confirmed to mention a specific product — each "
    "region carries an index, a timestamp, the spoken text, and a note on why "
    "it refers to the product.\n\n"
    "Your job: group these regions into exactly the requested number of short "
    "video edits, each explaining the product to someone who was not present "
    "at the live stream. Reference regions only by their given index — never "
    "invent regions that are not in the list.\n\n"
    "Guidelines:\n"
    "- Produce exactly the requested number of shorts.\n"
    "- Each short selects one or more regions whose combined length is roughly "
    "the target duration. A region may be reused across shorts only if there "
    "are not enough distinct regions to fill every short.\n"
    "- Within a short, keep regions in chronological order (ascending index).\n"
    "- Make the shorts MEANINGFULLY DIFFERENT from one another: feature "
    "distinct regions and vary the aspect of the product emphasized. Do not "
    "return the same set of regions twice.\n"
    "- Avoid time-sensitive language (\"today only\", \"limited stock\", "
    "\"right now\") — these clips will be watched weeks or months later.\n\n"
    "For each short return: region_indices (the chosen region indices in "
    "chronological order), a global_rationale for the short, and a "
    "differentiation_note saying how this short differs from the others."
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


def build_mention_user_prompt(
    *,
    scene_groups: list[list[FullSttScene]],
    llm_label: str,
    spoken_aliases: list[str],
) -> str:
    """Format the mention-extraction prompt: chunk headers + per-scene lines.

    Each scene gets a flat 0-based ``scene_idx`` that the LLM uses to
    address mention regions. Chunk headers are visual context only —
    the addressable unit is the scene index.

    Empty groups are skipped silently.
    """
    flat_scenes: list[FullSttScene] = [s for group in scene_groups for s in group]
    total_ms = flat_scenes[-1].end_ms if flat_scenes else 0

    clean_aliases = [a for a in (spoken_aliases or []) if a and a != llm_label]
    alias_str = ", ".join(clean_aliases) if clean_aliases else "(no aliases)"

    lines = [
        f"Product: {llm_label} (also called: {alias_str})",
        f"Source: {_ms_to_mmss(total_ms)}",
        "",
        (
            f"Transcript ({len(flat_scenes)} scenes in {len(scene_groups)} "
            f"chunks, chronological, scene_idx 0-indexed):"
        ),
    ]

    scene_idx = 0
    for chunk_i, group in enumerate(scene_groups):
        if not group:
            continue
        chunk_start = _ms_to_mmss(group[0].start_ms)
        chunk_end = _ms_to_mmss(group[-1].end_ms)
        lines.append("")
        lines.append(f"── Chunk {chunk_i} ({chunk_start}-{chunk_end}) ──")
        for scene in group:
            start_str = _ms_to_mmss(scene.start_ms)
            end_str = _ms_to_mmss(scene.end_ms)
            text = scene.text.replace('"', "'")
            lines.append(f'[{scene_idx}] {start_str}-{end_str} "{text}"')
            scene_idx += 1

    return "\n".join(lines)


def build_grouping_user_prompt(
    *,
    regions: list[tuple[int, int, str, str]],
    target_duration_ms: int,
    n: int,
) -> str:
    """User-turn prompt for ``pick_many`` stage 2: group regions into ``n``
    shorts.

    ``regions`` is the stage-1 mention list, pre-flattened by the picker into
    ``(start_ms, end_ms, text, rationale)`` tuples so this module stays free
    of schema/picker imports. Each region is listed with its 0-based index —
    the index the model returns in ``region_indices``.
    """
    target_s = target_duration_ms // 1000
    lines = [
        f"Produce exactly {n} shorts, each approximately {target_s}s, that are "
        f"meaningfully different from one another.",
        "",
        f"Mention regions ({len(regions)}, chronological, index 0-based):",
    ]
    for idx, (start_ms, end_ms, text, rationale) in enumerate(regions):
        start_str = _ms_to_mmss(start_ms)
        end_str = _ms_to_mmss(end_ms)
        clean_text = (text or "").replace('"', "'")
        line = f'[{idx}] {start_str}-{end_str} "{clean_text}"'
        if rationale:
            line += f" — {rationale}"
        lines.append(line)
    return "\n".join(lines)
