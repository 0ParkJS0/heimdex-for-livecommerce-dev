"""Story-shaped deterministic planner for purchase-focused shorts.

This module is the production extraction of the locally validated story-mode
experiment. It is intentionally pure: no DB sessions, OpenSearch clients,
network calls, or render-job concerns. Callers provide already-loaded scenes and
product context; the planner returns the existing ``FullSttClipPlan`` shape.

Compared to the contiguous purchase planner, this planner may select
non-contiguous source windows and concatenate them into a simple product story:
intro -> proof -> optional proof -> offer. It rejects live-commerce-only reward
language (samples, giveaways, review rewards, chat rewards) and penalizes
competing product terms so the result stays product-grounded.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.modules.shorts_auto_product.track_stt.full_stt.types import (
    FullSttClipPlan,
    FullSttSegment,
)
from app.modules.shorts_auto_product.track_stt.purchase_planner import (
    ProductNarrativeContext,
    PurchaseNarrativeScene,
)

_GIFT_PATTERNS = (
    "사은품",
    "사은",
    "선물",
    "증정",
    "챙겨드",
    "뽑아드",
    "보내드",
    "구매 인증",
    "구매인증",
    "샘플",
    "sample",
    "추첨",
    "당첨",
    "경품",
    "이벤트",
    "소통왕",
    "소통",
    "포토 리뷰",
    "리뷰 작성",
    "덤",
    "gift",
    "giveaway",
    "freebie",
)
_BENEFIT_PATTERNS = (
    "좋",
    "예쁘",
    "편하",
    "고급",
    "깔끔",
    "부드",
    "촉촉",
    "가볍",
    "탄탄",
    "맛있",
    "시원",
    "신선",
    "데일리",
    "활용",
    "보습",
    "향",
)
_DEMO_PATTERNS = (
    "보여",
    "보이",
    "착용",
    "신어",
    "발라",
    "먹",
    "드셔",
    "열어",
    "사용",
    "활용",
    "코디",
    "연출",
    "사이즈",
    "컬러",
    "색상",
    "구성",
)
_FEATURE_PATTERNS = (
    "소재",
    "굽",
    "쿠션",
    "스트랩",
    "용량",
    "키로",
    "국산",
    "원재료",
    "케이스",
    "패키지",
    "제형",
    "텍스처",
)
_OFFER_PATTERNS = (
    "가격",
    "할인",
    "특가",
    "혜택",
    "쿠폰",
    "무료배송",
    "배송",
    "구매",
    "주문",
    "원",
    "%",
    "세일",
)
_CTA_PATTERNS = (
    "구매",
    "주문",
    "담아",
    "클릭",
    "선택",
    "가져가",
    "추천",
    "지금",
    "오늘",
    "놓치",
)
_INTRO_PATTERNS = (
    "소개",
    "상품",
    "제품",
    "이거",
    "요거",
    "바로",
    "먼저",
    "오늘",
)

_ROLES = ("intro", "proof", "offer")


@dataclass(frozen=True)
class ProductStoryCandidate:
    rows: tuple[PurchaseNarrativeScene, ...]
    role: str
    score: float
    product_score: float
    competitor_score: float
    gift_penalty: float
    visual_score: float
    signals: tuple[str, ...]
    rationale: str

    @property
    def start_ms(self) -> int:
        return self.rows[0].start_ms

    @property
    def end_ms(self) -> int:
        return self.rows[-1].end_ms

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def plan_purchase_story_shorts(
    *,
    scenes: list[PurchaseNarrativeScene],
    product: ProductNarrativeContext,
    sibling_products: list[ProductNarrativeContext] | None = None,
    target_duration_ms: int,
    n: int,
    min_combo_score: float = 140.0,
) -> list[FullSttClipPlan]:
    """Return up to ``n`` product-story plans.

    Story mode does not create positional fallbacks. Returning fewer than ``n``
    means the source did not contain enough product-grounded story candidates;
    callers should leave those children without a render rather than produce a
    low-quality short.
    """
    if n <= 0:
        return []

    usable_scenes = sorted(
        [s for s in scenes if s.scene_id and s.end_ms > s.start_ms],
        key=lambda s: s.start_ms,
    )
    if not usable_scenes:
        return []

    product_terms = _terms([product.label, *product.aliases])
    if not product_terms:
        return []

    competitor_terms = _terms(
        term
        for sibling in sibling_products or []
        if sibling.label != product.label
        for term in [sibling.label, *sibling.aliases]
    )
    scene_windows = _candidate_scene_windows(usable_scenes)
    scored_by_role = {
        role: sorted(
            (
                _score_candidate(
                    rows,
                    role=role,
                    product=product,
                    product_terms=product_terms,
                    competitor_terms=competitor_terms,
                )
                for rows in scene_windows
            ),
            key=lambda c: (-c.score, c.start_ms),
        )
        for role in _ROLES
    }
    filtered_by_role = {
        role: [
            candidate
            for candidate in candidates
            if candidate.score > 0
            and candidate.product_score >= 5.0
            and candidate.gift_penalty == 0
            and candidate.competitor_score <= max(10.0, candidate.product_score * 1.2)
        ][:20]
        for role, candidates in scored_by_role.items()
    }

    combos: list[tuple[float, tuple[ProductStoryCandidate, ...]]] = []
    for intro in filtered_by_role["intro"][:10]:
        for proof1 in filtered_by_role["proof"][:12]:
            if _overlaps(intro, proof1):
                continue
            for offer in filtered_by_role["offer"][:12]:
                if _overlaps(offer, intro) or _overlaps(offer, proof1):
                    continue
                combo: list[ProductStoryCandidate] = [intro, proof1, offer]
                for proof2 in filtered_by_role["proof"][:12]:
                    if proof2 == proof1 or any(_overlaps(proof2, c) for c in combo):
                        continue
                    if abs(proof2.start_ms - proof1.start_ms) > target_duration_ms:
                        continue
                    if (
                        sum(c.duration_ms for c in combo) + proof2.duration_ms
                        <= target_duration_ms + 8_000
                    ):
                        combo.insert(2, proof2)
                    break
                duration_ms = sum(c.duration_ms for c in combo)
                if duration_ms < 32_000 or duration_ms > target_duration_ms + 10_000:
                    continue
                span_ms = max(c.end_ms for c in combo) - min(c.start_ms for c in combo)
                if span_ms > target_duration_ms + 60_000:
                    continue
                gap_penalty = max(0.0, (span_ms - duration_ms) / 1000.0)
                combo_score = (
                    sum(c.score for c in combo)
                    + min(15.0, duration_ms / 4000.0)
                    + (20.0 if len({s for c in combo for s in c.signals}) >= 4 else 0.0)
                    - gap_penalty
                )
                if combo_score >= min_combo_score:
                    combos.append((combo_score, tuple(combo)))

    combos.sort(key=lambda item: (-item[0], item[1][0].start_ms))
    plans: list[FullSttClipPlan] = []
    used_ranges: list[tuple[int, int]] = []
    for combo_score, combo in combos:
        combo_range = (min(c.start_ms for c in combo), max(c.end_ms for c in combo))
        if any(
            combo_range[0] < used_end and used_start < combo_range[1]
            for used_start, used_end in used_ranges
        ):
            continue
        plans.append(_plan_from_combo(product=product, combo=combo, combo_score=combo_score))
        used_ranges.append(combo_range)
        if len(plans) >= n:
            break
    return plans


def _terms(raw_terms: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        if not raw:
            continue
        for piece in [raw, *re.split(r"[\s,/()]+", raw)]:
            term = piece.strip()
            key = term.casefold()
            if len(key) < 2 or key in seen:
                continue
            seen.add(key)
            out.append(term)
    return out


def _contains(text: str, patterns: Iterable[str]) -> int:
    folded = text.casefold()
    return sum(1 for pattern in patterns if pattern.casefold() in folded)


def _score_product(scene: PurchaseNarrativeScene, product_terms: list[str]) -> float:
    score = 0.0
    transcript = scene.transcript.casefold()
    ocr = scene.ocr.casefold()
    caption = scene.caption.casefold()
    for term in product_terms:
        folded = term.casefold()
        if folded in transcript:
            score += 5.0
        if folded in ocr:
            score += 5.0
        if folded in caption:
            score += 3.0
    return score


def _score_visual(scene: PurchaseNarrativeScene, product_terms: list[str]) -> float:
    ocr_caption = " ".join([scene.ocr, scene.caption]).casefold()
    score = 0.0
    for term in product_terms:
        if term.casefold() in ocr_caption:
            score += 4.0
    if _contains(scene.text, _DEMO_PATTERNS):
        score += 3.0
    return score


def _signals(text: str) -> tuple[str, ...]:
    found: list[str] = []
    if _contains(text, _INTRO_PATTERNS):
        found.append("intro")
    if _contains(text, _BENEFIT_PATTERNS):
        found.append("benefit")
    if _contains(text, _DEMO_PATTERNS):
        found.append("demo")
    if _contains(text, _FEATURE_PATTERNS):
        found.append("feature")
    if _contains(text, _OFFER_PATTERNS):
        found.append("offer")
    if _contains(text, _CTA_PATTERNS):
        found.append("cta")
    return tuple(found)


def _candidate_scene_windows(
    scenes: list[PurchaseNarrativeScene],
) -> list[tuple[PurchaseNarrativeScene, ...]]:
    windows: list[tuple[PurchaseNarrativeScene, ...]] = []
    for start_idx in range(len(scenes)):
        rows: list[PurchaseNarrativeScene] = []
        for scene in scenes[start_idx:]:
            if rows and scene.start_ms - rows[-1].end_ms > 3000:
                break
            rows.append(scene)
            duration_ms = rows[-1].end_ms - rows[0].start_ms
            if duration_ms > 18_000:
                break
            if duration_ms >= 4_000:
                windows.append(tuple(rows))
    return windows


def _score_candidate(
    rows: tuple[PurchaseNarrativeScene, ...],
    *,
    role: str,
    product: ProductNarrativeContext,
    product_terms: list[str],
    competitor_terms: list[str],
) -> ProductStoryCandidate:
    text = " ".join(row.text for row in rows)
    product_score = sum(_score_product(row, product_terms) for row in rows)
    competitor_score = sum(_score_product(row, competitor_terms) for row in rows)
    visual_score = sum(_score_visual(row, product_terms) for row in rows)
    gift_penalty = min(80.0, _contains(text, _GIFT_PATTERNS) * 25.0)
    sigs = _signals(text)
    role_bonus = 0.0
    if role == "intro":
        role_bonus += 12.0 if "intro" in sigs else 0.0
        role_bonus += 10.0 if product_score >= 8.0 else 0.0
    elif role == "proof":
        role_bonus += 12.0 if {"benefit", "demo", "feature"} & set(sigs) else 0.0
        role_bonus += min(18.0, visual_score)
    elif role == "offer":
        role_bonus += 14.0 if {"offer", "cta"} & set(sigs) else 0.0
        role_bonus += 8.0 if product_score >= 5.0 else 0.0

    if product.first_mention_ms is not None and role == "intro":
        distance_s = abs(rows[0].start_ms - product.first_mention_ms) / 1000.0
        if distance_s <= 240:
            role_bonus += max(0.0, 8.0 - distance_s / 30.0)

    score = product_score * 2.0 + role_bonus + visual_score
    score -= competitor_score * 1.8
    score -= gift_penalty
    if product_score < 5.0:
        score -= 35.0
    if gift_penalty:
        score -= 50.0
    if competitor_score > max(10.0, product_score * 1.2):
        score -= 40.0
    if role == "proof" and not ({"benefit", "demo", "feature"} & set(sigs)):
        score -= 30.0
    if role == "offer" and not ({"offer", "cta"} & set(sigs)):
        score -= 30.0

    return ProductStoryCandidate(
        rows=rows,
        role=role,
        score=round(score, 3),
        product_score=round(product_score, 3),
        competitor_score=round(competitor_score, 3),
        gift_penalty=round(gift_penalty, 3),
        visual_score=round(visual_score, 3),
        signals=sigs,
        rationale=(
            f"story_role={role}; product_score={product_score:.1f}; "
            f"visual_score={visual_score:.1f}; competitor_score={competitor_score:.1f}; "
            f"gift_penalty={gift_penalty:.1f}; signals={','.join(sigs)}"
        ),
    )


def _overlaps(left: ProductStoryCandidate, right: ProductStoryCandidate) -> bool:
    return left.start_ms < right.end_ms and right.start_ms < left.end_ms


def _plan_from_combo(
    *,
    product: ProductNarrativeContext,
    combo: tuple[ProductStoryCandidate, ...],
    combo_score: float,
) -> FullSttClipPlan:
    segments: list[FullSttSegment] = []
    for candidate in combo:
        for row in candidate.rows:
            segments.append(
                FullSttSegment(
                    scene_id=row.scene_id,
                    source_start_ms=row.start_ms,
                    source_end_ms=row.end_ms,
                    rationale=candidate.rationale,
                )
            )
    rationale = (
        f"Story purchase plan for {product.label}; roles="
        + " > ".join(candidate.role for candidate in combo)
        + f"; combo_score={combo_score:.1f}"
    )
    return FullSttClipPlan(
        segments=segments,
        total_duration_ms=sum(segment.duration_ms for segment in segments),
        global_rationale=rationale,
        fallback_used=False,
    )


__all__ = [
    "ProductStoryCandidate",
    "plan_purchase_story_shorts",
]
