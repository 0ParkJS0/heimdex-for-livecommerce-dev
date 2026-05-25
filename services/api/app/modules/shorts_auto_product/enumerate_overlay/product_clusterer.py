"""Cluster per-keyframe extractions into a per-video product catalog.

For each video the extractor returns one row per (scene, product
mention). The same product typically appears in many scenes so we
fuzzy-match by name and collapse into one ``OverlayProduct`` per
unique product.

Filters drop promo / discount-only / bare-brand entries that the
extractor sometimes produces despite the prompt's instructions.

Pure module. No IO, no network.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.modules.shorts_auto_product.enumerate_overlay.service import (
    OverlayAppearance,
    OverlayProduct,
)

logger = logging.getLogger(__name__)


DEFAULT_SIMILARITY = 0.80


# Promo / giveaway keywords. Entries whose name contains any of these
# are treated as not-a-product noise.
_PROMO_KEYWORDS = (
    "gift", "사은품", "사은", "증정", "전구매", "쿠폰", "추첨", "응모", "당첨",
    "이벤트", "체험단", "체험딜",
)

# Bare-brand names that occasionally slip past the LLM as "product"
# entries. Conservative list -- only entries that have shown up in
# false positives during workspace experiments.
_BRAND_ONLY = frozenset({
    "hera", "hera markgong", "센트룸", "센트롬", "osulloc", "오설록",
    "jongga", "종가", "acebiome", "동국제약", "dongkook",
    "신지모루", "비에날", "비에날퀸",
})


@dataclass(frozen=True)
class ProductExtraction:
    """One ``(scene, product_mention)`` row from the extractor."""

    scene_id: str
    timestamp_ms: int
    detector_score: float
    extracted_name: str
    extracted_price: int | None
    # Optional layout slot ('top-left' .. 'full-frame'). Absent in
    # earlier prompt versions.
    position: str | None


def _is_promo_or_noise(name: str) -> tuple[bool, str | None]:
    """Return ``(is_noise, reason)`` for one extracted name."""
    if not name or not name.strip():
        return True, "empty"
    raw = name.strip()
    lowered = raw.lower()

    for kw in _PROMO_KEYWORDS:
        if kw in lowered:
            return True, f"promo:{kw}"

    has_price = bool(
        re.search(r"\d{1,3}(?:[,.]?\d{3})+\s*원|\d{4,}\s*원", raw)
    )
    has_discount = bool(re.search(r"\d+\s*%|off", lowered))
    rest = re.sub(
        r"\d{1,3}(?:[,.]?\d{3})+\s*원|\d{4,}\s*원|\d+\s*%|off|할인가|할인",
        "",
        lowered,
    )
    rest = re.sub(r"[\s,.\-]+", "", rest)
    if has_price and has_discount and len(rest) < 3:
        return True, "discount_banner"

    collapsed = re.sub(r"\s+", " ", lowered).strip()
    if collapsed in _BRAND_ONLY:
        return True, f"brand_only:{collapsed}"

    if len(re.sub(r"\s+", "", raw)) <= 2:
        return True, "too_short"

    return False, None


def _normalize_for_match(s: str) -> str:
    """Normalize a name for fuzzy-match comparison."""
    s = s.lower()
    s = re.sub(r"[\[\]()【】〔〕]", " ", s)
    s = re.sub(r"[xX×]\s*\d+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(
        None, _normalize_for_match(a), _normalize_for_match(b)
    ).ratio()


def cluster_products(
    *,
    extractions: list[ProductExtraction],
    video_drive_id: str,
    similarity: float = DEFAULT_SIMILARITY,
) -> list[OverlayProduct]:
    """Cluster extractions into one ``OverlayProduct`` per unique product.

    Args:
        extractions: All ``(scene, mention)`` rows from one video.
        video_drive_id: ``gd_<hash>`` -- used to build deterministic
            ``product_id`` values.
        similarity: ``SequenceMatcher`` ratio threshold for two names
            to be considered the same product.

    Returns:
        ``OverlayProduct`` list, sorted by first appearance.
        ``image_s3_key`` is always ``None`` here; the image picker
        fills it later via ``dataclasses.replace``.
    """
    flat: list[ProductExtraction] = []
    dropped: Counter[str] = Counter()
    for item in extractions:
        is_noise, reason = _is_promo_or_noise(item.extracted_name)
        if is_noise:
            dropped[reason or "unknown"] += 1
            continue
        flat.append(item)
    if dropped:
        logger.info(
            "overlay_clusterer_dropped",
            extra={"video_id": video_drive_id, "dropped": dict(dropped)},
        )

    # Sort by name length so the most-specific names anchor clusters.
    flat.sort(key=lambda x: -len(x.extracted_name))

    # Internal mutable scratch records; converted to OverlayProduct at the end.
    clusters: list[dict] = []
    for item in flat:
        match: dict | None = None
        best_sim = 0.0
        for cluster in clusters:
            sim = _name_similarity(item.extracted_name, cluster["canonical"])
            if sim >= similarity and sim > best_sim:
                match = cluster
                best_sim = sim
        if match is not None:
            match["all_names"].append(item.extracted_name)
            match["all_prices"].append(item.extracted_price)
            match["appearances"].append(item)
        else:
            clusters.append({
                "canonical": item.extracted_name,
                "all_names": [item.extracted_name],
                "all_prices": [item.extracted_price],
                "appearances": [item],
            })

    products: list[OverlayProduct] = []
    for cluster in clusters:
        name_counts = Counter(cluster["all_names"])
        canonical = name_counts.most_common(1)[0][0]

        prices = [p for p in cluster["all_prices"] if p is not None]
        price = Counter(prices).most_common(1)[0][0] if prices else None

        positions = [
            a.position for a in cluster["appearances"] if a.position
        ]
        position = (
            Counter(positions).most_common(1)[0][0] if positions else "full-frame"
        )

        # Best representative -- highest detector score wins.
        best = max(cluster["appearances"], key=lambda a: a.detector_score)

        # Dedup variants while preserving order.
        seen: set[str] = set()
        variants: list[str] = []
        for n in cluster["all_names"]:
            if n not in seen:
                seen.add(n)
                variants.append(n)

        appearances = tuple(
            OverlayAppearance(
                scene_id=a.scene_id,
                timestamp_ms=a.timestamp_ms,
                detector_score=a.detector_score,
                extracted_name=a.extracted_name,
                extracted_price=a.extracted_price,
            )
            for a in sorted(cluster["appearances"], key=lambda x: x.timestamp_ms)
        )

        products.append(
            OverlayProduct(
                # product_id assigned after sort.
                product_id="",
                name=canonical,
                price=price,
                position=position,
                best_scene_id=best.scene_id,
                image_s3_key=None,
                appearances=appearances,
                name_variants=tuple(variants),
            )
        )

    products.sort(key=lambda p: p.appearances[0].timestamp_ms)

    from dataclasses import replace

    return [
        replace(p, product_id=f"{video_drive_id}_p{i:03d}")
        for i, p in enumerate(products, start=1)
    ]
