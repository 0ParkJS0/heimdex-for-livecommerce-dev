"""Slot-assembler for an overlay-driven short.

Given a product, its overlay segments, and the video's STT + silence
intervals, choose HOOK / HERO / DEMO(s) / CLOSE slots and return a
:class:`ShortsAssembly` plan. The plan is consumed by a downstream
ffmpeg worker; this module does not call ffmpeg itself.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Literal

from app.modules.shorts_auto_product.overlay_shorts.enumeration_result import (
    OverlayProduct,
)
from app.modules.shorts_auto_product.overlay_shorts.service import (
    DurationPreset,
    OverlaySegment,
    ShortsAssembly,
    ShortsSlot,
    SttSegment,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vocabulary.

_HOOK_KEYWORDS = ("안녕", "여러분", "오늘", "지금부터", "준비했")
_CLOSE_KEYWORDS = ("감사합", "수고하셨", "마무리", "다음 시간", "다음에")
# Phrases that signal a *false* close moment (event / quiz endings).
_CLOSE_STOPWORDS = ("범인", "정답", "추첨", "당첨", "이벤트", "퀴즈")
# Texture / usage descriptors -- bonus signal for DEMO clusters.
_DEMO_DESCRIPTORS = (
    "쫀득", "꾸덕", "흡수", "촉촉", "산뜻", "쫄깃", "물 젤리", "수분", "보송",
    "발색", "발림", "쓱싹", "스르르", "유분", "글로우", "매트", "물 터지",
    "리치", "쫙", "펴 바르", "올렸을",
)

_FILLER_CHARS = "네응예아오"
_KOREAN_SENTENCE_FINAL = frozenset("다요죠까네어야니라")

# Per-target-duration slot budgets in seconds. ``demo_clusters`` is
# the number of distinct STT clusters that share the DEMO budget at
# longer durations.
_SLOT_BUDGETS: dict[DurationPreset, dict[str, float]] = {
    15:  {"HOOK": 2.5, "HERO": 4.0, "DEMO": 6.0,  "CLOSE": 2.5, "demo_clusters": 1.0},
    30:  {"HOOK": 3.0, "HERO": 5.0, "DEMO": 18.0, "CLOSE": 4.0, "demo_clusters": 1.0},
    60:  {"HOOK": 4.0, "HERO": 7.0, "DEMO": 42.0, "CLOSE": 7.0, "demo_clusters": 2.0},
    90:  {"HOOK": 4.0, "HERO": 8.0, "DEMO": 65.0, "CLOSE": 13.0, "demo_clusters": 3.0},
    120: {"HOOK": 5.0, "HERO": 10.0, "DEMO": 90.0, "CLOSE": 15.0, "demo_clusters": 3.0},
}

# Padding / silence-snap parameters.
_PAD_LEAD = 2.00
_PAD_TAIL = 2.00
_HARD_PAD_LEAD = 0.15
_HARD_PAD_TAIL = 0.25
_SENTENCE_END_PAD = 0.50


# ---------------------------------------------------------------------------
# STT helpers.


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _is_music_or_filler(seg: SttSegment) -> bool:
    """Detect STT segments that look like music intervals or filler stacks."""
    text = seg.text.strip()
    dur = seg.end_s - seg.start_s
    if dur <= 0:
        return True
    stripped = "".join(c for c in text if c not in " .,!?~ㅋㅎ\t\n")
    if stripped and all(c in _FILLER_CHARS for c in stripped):
        return True
    filler_count = sum(
        len(re.findall(rf"\b{f}\b|{f}\s*\.|{f}\s*$", text))
        for f in _FILLER_CHARS
    )
    if filler_count >= 5:
        return True
    char_per_s = len(text.replace(" ", "")) / dur
    if dur >= 10 and char_per_s < 1.5:
        return True
    return False


def _ends_in_sentence_final(text: str) -> bool:
    stripped = text.rstrip(" .,!?~ㅋㅎ\t\n")
    return bool(stripped) and stripped[-1] in _KOREAN_SENTENCE_FINAL


def _cluster_duration(cluster: list[SttSegment]) -> float:
    return cluster[-1].end_s - cluster[0].start_s


def _cluster_text(cluster: list[SttSegment]) -> str:
    return " ".join(s.text for s in cluster)


def _find_product_mentions(
    stt: list[SttSegment], keywords: list[str]
) -> list[SttSegment]:
    return [
        s for s in stt
        if any(k in s.text for k in keywords) and not _is_music_or_filler(s)
    ]


def _cluster_temporal(
    segs: list[SttSegment], gap_s: float
) -> list[list[SttSegment]]:
    segs = sorted(segs, key=lambda s: s.start_s)
    if not segs:
        return []
    clusters: list[list[SttSegment]] = [[segs[0]]]
    for s in segs[1:]:
        if s.start_s - clusters[-1][-1].end_s > gap_s:
            clusters.append([s])
        else:
            clusters[-1].append(s)
    return clusters


def _expand_cluster_to_duration(
    seed: list[SttSegment],
    stt: list[SttSegment],
    target_s: float,
    max_gap_s: float = 8.0,
) -> list[SttSegment]:
    """Grow a cluster outward in time until it roughly hits ``target_s``."""
    if _cluster_duration(seed) >= target_s:
        return seed
    try:
        first_idx = next(i for i, s in enumerate(stt) if s.start_s == seed[0].start_s)
        last_idx = next(i for i, s in enumerate(stt) if s.end_s == seed[-1].end_s)
    except StopIteration:
        return seed
    cur = list(seed)
    bi, fi = first_idx - 1, last_idx + 1
    while _cluster_duration(cur) < target_s and (bi >= 0 or fi < len(stt)):
        if fi < len(stt) and (stt[fi].start_s - cur[-1].end_s) <= max_gap_s:
            cur.append(stt[fi])
            fi += 1
        elif bi >= 0 and (cur[0].start_s - stt[bi].end_s) <= max_gap_s:
            cur.insert(0, stt[bi])
            bi -= 1
        else:
            break
        if _cluster_duration(cur) >= target_s * 1.2:
            break
    return cur


def _trim_cluster_to_duration(
    cluster: list[SttSegment], target_s: float
) -> list[SttSegment]:
    while len(cluster) > 1 and _cluster_duration(cluster) > target_s:
        cluster.pop()
    if _cluster_duration(cluster) > target_s:
        cluster = list(cluster)
        last = cluster[-1]
        cluster[-1] = SttSegment(
            start_s=last.start_s,
            end_s=cluster[0].start_s + target_s,
            text=last.text,
        )
    return cluster


# ---------------------------------------------------------------------------
# Slot pickers.


def _pick_hook(
    stt: list[SttSegment], budget_s: float, search_window_s: float = 900.0
) -> tuple[list[SttSegment], str]:
    early = [
        s for s in stt
        if s.start_s <= search_window_s and not _is_music_or_filler(s)
    ]
    candidates = [
        s for s in early
        if any(k in s.text for k in _HOOK_KEYWORDS)
        and len(s.text) <= 30
        and (s.end_s - s.start_s) <= 5.0
    ]
    if not candidates:
        candidates = [
            s for s in early if any(k in s.text for k in _HOOK_KEYWORDS)
        ]
    if not candidates:
        candidates = sorted(early, key=lambda s: s.end_s - s.start_s)[:3]
    if not candidates:
        # Pathological -- no usable sentences at all.
        return [], "no_hook"
    candidates.sort(key=lambda s: (
        0 if any(k in s.text for k in _HOOK_KEYWORDS) else 1,
        s.start_s,
    ))
    pick = candidates[0]
    idx = stt.index(pick)
    expanded = [pick]
    while (
        idx + 1 < len(stt)
        and (stt[idx + 1].end_s - expanded[0].start_s) <= budget_s + 1
    ):
        if _is_music_or_filler(stt[idx + 1]):
            break
        expanded.append(stt[idx + 1])
        idx += 1
    return expanded, "earliest_greeting"


def _pick_close(
    stt: list[SttSegment],
    video_duration_s: float,
    budget_s: float,
    search_window_s: float = 600.0,
) -> tuple[list[SttSegment], str]:
    late = [
        s for s in stt
        if s.start_s >= video_duration_s - search_window_s
        and not _is_music_or_filler(s)
    ]
    candidates = [
        s for s in late
        if any(k in s.text for k in _CLOSE_KEYWORDS)
        and not any(sw in s.text for sw in _CLOSE_STOPWORDS)
    ]
    if not candidates:
        candidates = [
            s for s in late
            if not any(sw in s.text for sw in _CLOSE_STOPWORDS)
            and (s.end_s - s.start_s) <= 6.0
        ]
    if not candidates:
        candidates = [s for s in late[-3:] if not _is_music_or_filler(s)] or late[-3:]
    if not candidates:
        return [], "no_close"
    candidates.sort(key=lambda s: -s.start_s)
    pick = candidates[0]
    idx = stt.index(pick)
    expanded = [pick]
    while (
        idx - 1 >= 0
        and (expanded[-1].end_s - stt[idx - 1].start_s) <= budget_s + 1
    ):
        if _is_music_or_filler(stt[idx - 1]):
            break
        expanded.insert(0, stt[idx - 1])
        idx -= 1
    return expanded, "latest_closing"


def _score_demo_cluster(
    cluster: list[SttSegment],
    overlay_windows: list[tuple[float, float]],
    max_dur_s: float,
) -> float:
    dur = min(_cluster_duration(cluster), max_dur_s)
    text = _cluster_text(cluster)
    n_descs = sum(1 for d in _DEMO_DESCRIPTORS if d in text)
    desc_bonus = 1.0 + min(n_descs * 0.15, 0.6)
    cs, ce = cluster[0].start_s, cluster[-1].end_s
    overlap_bonus = 1.0
    for o_start, o_end in overlay_windows:
        if cs < o_end and o_start < ce:
            overlap_bonus = 1.25
            break
    return dur * desc_bonus * overlap_bonus


def _pick_demo_multi(
    stt: list[SttSegment],
    product_keywords: list[str],
    overlay_windows: list[tuple[float, float]],
    total_budget_s: float,
    n_clusters: int,
) -> tuple[list[list[SttSegment]], str]:
    mentions = _find_product_mentions(stt, product_keywords)
    if not mentions:
        return [], "no_mentions"
    clusters = _cluster_temporal(mentions, gap_s=10.0)
    if not clusters:
        return [], "no_clusters"
    scored = [(_score_demo_cluster(c, overlay_windows, total_budget_s), c)
              for c in clusters]
    scored.sort(key=lambda x: -x[0])
    picks: list[list[SttSegment]] = []
    remaining = total_budget_s
    per_cluster_budget = total_budget_s / max(n_clusters, 1)
    for _, cluster in scored:
        if remaining <= 0 or len(picks) >= n_clusters:
            break
        target = min(per_cluster_budget, remaining)
        if _cluster_duration(cluster) < target:
            cluster = _expand_cluster_to_duration(cluster, stt, target)
        cluster = _trim_cluster_to_duration(cluster, target)
        if _cluster_duration(cluster) < 2.0:
            continue
        picks.append(cluster)
        remaining -= _cluster_duration(cluster)
    picks.sort(key=lambda c: c[0].start_s)
    return picks, f"top_{len(picks)}_clusters"


def _pick_hero(
    product: OverlayProduct,
    overlay_segments: list[OverlaySegment],
    budget_s: float,
) -> tuple[float, float, str]:
    """Hero window centered on the product's overlay segment."""
    best_scene_id = product.best_scene_id
    target_seg: OverlaySegment | None = None
    for seg in overlay_segments:
        if best_scene_id in seg.scene_ids:
            target_seg = seg
            break
    if target_seg is None and overlay_segments:
        target_seg = overlay_segments[0]
    if target_seg is None:
        # No overlay segments at all -- fall back to the first appearance.
        first_ms = (
            product.appearances[0].timestamp_ms if product.appearances else 0
        )
        center = first_ms / 1000.0
    else:
        center = (target_seg.clip_start_s + target_seg.clip_end_s) / 2.0
    half = budget_s / 2.0
    return max(0.0, center - half), center + half, "overlay_segment_center"


# ---------------------------------------------------------------------------
# Silence-aware cuts.


def _snap_to_silence(
    target_s: float,
    silences: list[tuple[float, float]],
    direction: str,
    max_radius: float,
) -> float:
    candidates: list[float] = []
    for ss, se in silences:
        sm = (ss + se) / 2.0
        if direction == "backward" and sm <= target_s and (target_s - sm) <= max_radius:
            candidates.append(sm)
        elif direction == "forward" and sm >= target_s and (sm - target_s) <= max_radius:
            candidates.append(sm)
    if not candidates:
        return target_s
    return min(candidates, key=lambda x: abs(x - target_s))


def _pad_cut(
    start_s: float,
    end_s: float,
    silences: list[tuple[float, float]],
    end_text: str,
) -> tuple[float, float]:
    snapped_start = _snap_to_silence(start_s, silences, "backward", _PAD_LEAD)
    if snapped_start == start_s:
        snapped_start = max(0.0, start_s - _HARD_PAD_LEAD)
    snapped_end = _snap_to_silence(end_s, silences, "forward", _PAD_TAIL)
    if snapped_end == end_s:
        if _ends_in_sentence_final(end_text):
            snapped_end = end_s + _SENTENCE_END_PAD
        else:
            snapped_end = end_s + _HARD_PAD_TAIL
    return snapped_start, snapped_end


def _segs_window(segs: list[SttSegment]) -> tuple[float, float]:
    return segs[0].start_s, segs[-1].end_s


# ---------------------------------------------------------------------------
# Entry.


def _name_keywords(name: str, extra: list[str] | None = None) -> list[str]:
    tokens = [_norm(t) for t in name.split() if len(t) >= 2]
    if extra:
        tokens.extend(_norm(t) for t in extra)
    # Order-preserving dedup.
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def assemble_shorts_plan(
    *,
    product: OverlayProduct,
    overlay_segments: list[OverlaySegment],
    stt_segments: list[SttSegment],
    silences: list[tuple[float, float]],
    video_duration_s: float,
    source_video_locator: str,
    target_duration_s: DurationPreset = 60,
    extra_keywords: list[str] | None = None,
) -> ShortsAssembly:
    """Build a four-slot (HOOK / HERO / DEMO(s) / CLOSE) plan.

    ``ffmpeg`` is not invoked -- the returned :class:`ShortsAssembly`
    is consumed downstream by a renderer.
    """
    if target_duration_s not in _SLOT_BUDGETS:
        raise ValueError(
            f"target_duration_s must be one of "
            f"{sorted(_SLOT_BUDGETS.keys())}, got {target_duration_s}"
        )
    budgets = _SLOT_BUDGETS[target_duration_s]
    n_demo_clusters = int(budgets["demo_clusters"])
    keywords = _name_keywords(product.name, extra_keywords)

    overlay_windows = [
        (s.clip_start_s, s.clip_end_s) for s in overlay_segments
    ]

    hook_segs, hook_reason = _pick_hook(stt_segments, budgets["HOOK"])
    close_segs, close_reason = _pick_close(
        stt_segments, video_duration_s, budgets["CLOSE"]
    )
    demo_clusters, demo_reason = _pick_demo_multi(
        stt_segments,
        keywords,
        overlay_windows,
        budgets["DEMO"],
        n_demo_clusters,
    )
    hero_start, hero_end, hero_reason = _pick_hero(
        product, overlay_segments, budgets["HERO"]
    )

    slots: list[ShortsSlot] = []

    if hook_segs:
        hs, he = _segs_window(hook_segs)
        hs, he = _pad_cut(hs, he, silences, hook_segs[-1].text)
        if he - hs < budgets["HOOK"]:
            he = hs + budgets["HOOK"]
        slots.append(ShortsSlot(
            name="HOOK",
            start_s=hs,
            end_s=he,
            text=" ".join(s.text for s in hook_segs),
            reason=hook_reason,
        ))

    slots.append(ShortsSlot(
        name="HERO",
        start_s=hero_start,
        end_s=hero_end,
        text="(overlay graphic moment)",
        reason=hero_reason,
    ))

    for i, cluster in enumerate(demo_clusters):
        ds, de = _segs_window(cluster)
        ds, de = _pad_cut(ds, de, silences, cluster[-1].text)
        suffix = f"_{i + 1}" if len(demo_clusters) > 1 else ""
        slots.append(ShortsSlot(
            name=f"DEMO{suffix}",
            start_s=ds,
            end_s=de,
            text=_cluster_text(cluster),
            reason=demo_reason,
        ))

    if close_segs:
        cs, ce = _segs_window(close_segs)
        cs, ce = _pad_cut(cs, ce, silences, close_segs[-1].text)
        if ce - cs < budgets["CLOSE"]:
            ce = cs + budgets["CLOSE"]
        slots.append(ShortsSlot(
            name="CLOSE",
            start_s=cs,
            end_s=ce,
            text=" ".join(s.text for s in close_segs),
            reason=close_reason,
        ))

    actual_dur = sum(s.end_s - s.start_s for s in slots)
    return ShortsAssembly(
        product_id=product.product_id,
        video_drive_id=overlay_segments[0].video_drive_id if overlay_segments
        else product.product_id.rsplit("_p", 1)[0],
        source_video_locator=source_video_locator,
        target_duration_s=target_duration_s,
        actual_duration_s=round(actual_dur, 3),
        slots=tuple(slots),
    )
