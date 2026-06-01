"""Deterministic product-grounded planner for purchase-focused shorts.

This module packages the locally validated experiment into the production
shared-plan shape. It does not call OpenAI: the catalog enumeration step has
already picked/verified the product, and this planner uses that product context
to select contiguous windows with both product evidence and buying signals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.modules.shorts_auto_product.track_stt.full_stt.types import (
    FullSttClipPlan,
    FullSttSegment,
)


@dataclass(frozen=True)
class PurchaseNarrativeScene:
    scene_id: str
    start_ms: int
    end_ms: int
    transcript: str = ""
    ocr: str = ""
    caption: str = ""

    @property
    def text(self) -> str:
        return " ".join(
            part for part in (self.transcript, self.ocr, self.caption) if part
        )


@dataclass(frozen=True)
class ProductNarrativeContext:
    label: str
    aliases: tuple[str, ...] = ()
    first_mention_ms: int | None = None
    example_quote: str | None = None


@dataclass(frozen=True)
class _ScoredScene:
    scene: PurchaseNarrativeScene
    score: float
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class _WindowScore:
    rows: list[PurchaseNarrativeScene]
    score: float
    product_score: float
    sales_score: float
    arc_score: float
    matched_terms: tuple[str, ...]
    matched_signals: tuple[str, ...]

    @property
    def start_ms(self) -> int:
        return self.rows[0].start_ms

    @property
    def end_ms(self) -> int:
        return self.rows[-1].end_ms


_SALES_SIGNAL_PATTERNS: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    (
        "benefit",
        6.0,
        (
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
            "아삭",
            "시원",
            "신선",
            "활용",
            "데일리",
            "매일",
            "입기",
            "바르",
            "보습",
            "발색",
            "향",
            "nice",
            "soft",
            "comfortable",
        ),
    ),
    (
        "demo_or_usage",
        7.0,
        (
            "보여",
            "보이",
            "착용",
            "신어",
            "발라",
            "먹",
            "드셔",
            "열어",
            "꺼내",
            "넣",
            "사용",
            "활용",
            "코디",
            "연출",
            "사이즈",
            "컬러",
            "색상",
            "제형",
            "텍스처",
            "구성",
            "use",
            "wear",
            "apply",
            "color",
        ),
    ),
    (
        "specific_feature",
        5.0,
        (
            "소재",
            "굽",
            "쿠션",
            "스트랩",
            "용량",
            "10kg",
            "키로",
            "포기",
            "국산",
            "원재료",
            "케이스",
            "패키지",
            "발림",
            "광택",
            "밀착",
            "feature",
            "texture",
            "package",
        ),
    ),
    (
        "price_or_offer",
        8.0,
        (
            "가격",
            "할인",
            "특가",
            "혜택",
            "쿠폰",
            "무료",
            "배송",
            "구매",
            "원",
            "%",
            "세일",
            "sale",
            "discount",
            "price",
            "free shipping",
        ),
    ),
    (
        "urgency",
        5.5,
        (
            "지금",
            "오늘",
            "이번",
            "마지막",
            "한정",
            "품절",
            "남았",
            "라이브",
            "기회",
            "놓치",
            "now",
            "today",
            "limited",
        ),
    ),
    (
        "cta",
        7.0,
        (
            "구매",
            "주문",
            "담아",
            "클릭",
            "선택",
            "가져가",
            "챙겨",
            "추천",
            "사세요",
            "하세요",
            "buy",
            "order",
            "click",
            "recommend",
        ),
    ),
    (
        "objection_handling",
        4.0,
        (
            "걱정",
            "부담",
            "괜찮",
            "문제",
            "교환",
            "반품",
            "보관",
            "오래",
            "쉽",
            "간편",
            "누구나",
            "아깝",
            "비싸",
            "아니",
            "concern",
        ),
    ),
)

_OPENING_TERMS = (
    "오늘",
    "소개",
    "보여",
    "상품",
    "제품",
    "이거",
    "요거",
    "바로",
    "먼저",
    "today",
    "this",
    "product",
)
_CLOSE_TERMS = (
    "구매",
    "주문",
    "담아",
    "지금",
    "오늘",
    "추천",
    "가져가",
    "놓치",
    "마지막",
    "buy",
    "order",
    "now",
    "recommend",
)


def plan_purchase_focused_shorts(
    *,
    scenes: list[PurchaseNarrativeScene],
    product: ProductNarrativeContext,
    target_duration_ms: int,
    n: int,
) -> list[FullSttClipPlan]:
    """Return ``n`` purchase-focused, product-grounded clip plans.

    The output intentionally reuses ``FullSttClipPlan`` so the existing
    product child runner can persist and render the result without a new render
    path. If no persuasive/product-grounded window exists, positional fallback
    plans are returned with ``fallback_used=True``.
    """
    if n <= 0:
        return []
    usable_scenes = sorted(
        [s for s in scenes if s.scene_id and s.end_ms > s.start_ms],
        key=lambda s: s.start_ms,
    )
    if not usable_scenes:
        return [_empty_plan("purchase_planner_no_scenes") for _ in range(n)]

    terms = _terms_for_product(product)
    scene_scores = {
        scene.scene_id: _score_scene(scene, product, terms) for scene in usable_scenes
    }
    candidates = _candidate_windows(
        usable_scenes,
        target_duration_ms=target_duration_ms,
        min_duration_ms=max(30_000, target_duration_ms - 12_000),
        max_duration_ms=target_duration_ms + 12_000,
    )
    windows = [
        _score_window(
            rows,
            product,
            scene_scores,
            target_duration_ms,
        )
        for rows in candidates
    ]
    windows = [
        w
        for w in windows
        if w.matched_terms and w.matched_signals and w.product_score > 0
    ]
    windows.sort(key=lambda w: (-w.score, w.start_ms))

    plans: list[FullSttClipPlan] = []
    used_ranges: list[tuple[int, int]] = []
    for window in windows:
        if any(
            window.start_ms < used_end and used_start < window.end_ms
            for used_start, used_end in used_ranges
        ):
            continue
        plans.append(_plan_from_window(window, product))
        used_ranges.append((window.start_ms, window.end_ms))
        if len(plans) >= n:
            break

    fallback_cursor = 0
    while len(plans) < n:
        plans.append(
            _positional_fallback(
                usable_scenes,
                target_duration_ms,
                positions=_FALLBACK_PATTERNS[fallback_cursor % len(_FALLBACK_PATTERNS)],
            )
        )
        fallback_cursor += 1
    return plans


def _terms_for_product(ctx: ProductNarrativeContext) -> list[str]:
    terms: list[str] = []
    for raw in [ctx.label, *ctx.aliases]:
        if not raw:
            continue
        terms.append(raw)
        terms.extend(t for t in re.split(r"[\s,/()]+", raw) if len(t) >= 2)
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.casefold().strip()
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        out.append(term.strip())
    return out


def _score_scene(
    scene: PurchaseNarrativeScene,
    ctx: ProductNarrativeContext,
    terms: list[str],
) -> _ScoredScene:
    matched: list[str] = []
    score = 0.0
    transcript = scene.transcript.casefold()
    ocr = scene.ocr.casefold()
    caption = scene.caption.casefold()
    for term in terms:
        t = term.casefold()
        term_score = 0.0
        if t in transcript:
            term_score += 5.0
        if t in ocr:
            term_score += 3.5
        if t in caption:
            term_score += 2.5
        if term_score:
            matched.append(term)
            score += term_score

    if ctx.example_quote:
        quote = ctx.example_quote.casefold()
        if quote and quote[:30] in transcript:
            score += 12.0
            matched.append("example_quote")

    if ctx.first_mention_ms is not None:
        distance_s = abs(scene.start_ms - ctx.first_mention_ms) / 1000.0
        if distance_s <= 180:
            score += max(0.0, 4.0 - distance_s / 45.0)

    if scene.transcript:
        score += 1.0
    return _ScoredScene(
        scene=scene,
        score=score,
        matched_terms=tuple(sorted(set(matched))),
    )


def _sales_signals_for_text(text: str) -> tuple[float, tuple[str, ...]]:
    folded = text.casefold()
    score = 0.0
    matched: list[str] = []
    for name, weight, patterns in _SALES_SIGNAL_PATTERNS:
        hits = sum(1 for pattern in patterns if pattern.casefold() in folded)
        if hits:
            matched.append(name)
            score += weight * min(2, hits)
    return score, tuple(sorted(set(matched)))


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    folded = text.casefold()
    return any(term.casefold() in folded for term in terms)


def _score_window(
    rows: list[PurchaseNarrativeScene],
    product: ProductNarrativeContext,
    scene_scores: dict[str, _ScoredScene],
    target_duration_ms: int,
) -> _WindowScore:
    texts = [row.text for row in rows]
    product_scene_scores = [scene_scores[row.scene_id] for row in rows]
    product_score = sum(item.score for item in product_scene_scores)
    product_scenes = [item for item in product_scene_scores if item.score > 0]
    product_density = len(product_scenes) / max(1, len(rows))
    matched_terms = sorted(
        {term for item in product_scene_scores for term in item.matched_terms}
    )

    sales_score = 0.0
    matched_signals: set[str] = set()
    for text in texts:
        score, signals = _sales_signals_for_text(text)
        sales_score += score
        matched_signals.update(signals)

    first_third = " ".join(texts[: max(1, len(texts) // 3)])
    middle_third = " ".join(
        texts[max(1, len(texts) // 3) : max(2, (len(texts) * 2) // 3)]
    )
    final_third = " ".join(texts[max(1, (len(texts) * 2) // 3) :])

    benefit_demo_feature_terms = tuple(
        pattern
        for name, _, patterns in _SALES_SIGNAL_PATTERNS
        if name in {"benefit", "demo_or_usage", "specific_feature"}
        for pattern in patterns
    )
    arc_score = 0.0
    if _contains_any(first_third, _OPENING_TERMS) or any(
        scene_scores[row.scene_id].score > 0 for row in rows[: max(1, len(rows) // 3)]
    ):
        arc_score += 8.0
    if _contains_any(middle_third, benefit_demo_feature_terms):
        arc_score += 10.0
    if _contains_any(final_third, _CLOSE_TERMS):
        arc_score += 8.0
    if {"benefit", "demo_or_usage"} & matched_signals and {
        "price_or_offer",
        "cta",
        "urgency",
    } & matched_signals:
        arc_score += 12.0
    if len(matched_signals) >= 3:
        arc_score += 5.0

    duration_delta = abs((rows[-1].end_ms - rows[0].start_ms) - target_duration_ms)
    duration_penalty = min(12.0, duration_delta / 5000.0)
    gap_penalty = 0.0
    for left, right in zip(rows, rows[1:]):
        gap_ms = max(0, right.start_ms - left.end_ms)
        if gap_ms > 1000:
            gap_penalty += min(5.0, gap_ms / 1000.0)

    score = (
        product_score * 1.4
        + sales_score
        + arc_score
        + 25.0 * product_density
        + (15.0 if len(product_scenes) >= 2 else 0.0)
        - duration_penalty
        - gap_penalty
    )
    if not matched_terms:
        score -= 100.0
    if not matched_signals:
        score -= 25.0
    if product_density < 0.20:
        score -= 20.0

    return _WindowScore(
        rows=rows,
        score=round(score, 3),
        product_score=round(product_score, 3),
        sales_score=round(sales_score, 3),
        arc_score=round(arc_score, 3),
        matched_terms=tuple(matched_terms),
        matched_signals=tuple(sorted(matched_signals)),
    )


def _candidate_windows(
    scenes: list[PurchaseNarrativeScene],
    *,
    target_duration_ms: int,
    min_duration_ms: int,
    max_duration_ms: int,
) -> list[list[PurchaseNarrativeScene]]:
    windows: list[list[PurchaseNarrativeScene]] = []
    for start_idx in range(len(scenes)):
        rows: list[PurchaseNarrativeScene] = []
        for scene in scenes[start_idx:]:
            if rows and scene.start_ms - rows[-1].end_ms > 3000:
                break
            rows.append(scene)
            duration_ms = rows[-1].end_ms - rows[0].start_ms
            if duration_ms > max_duration_ms:
                break
            if duration_ms >= min_duration_ms:
                windows.append(list(rows))
                if duration_ms >= target_duration_ms:
                    break
    return windows


def _plan_from_window(
    window: _WindowScore,
    product: ProductNarrativeContext,
) -> FullSttClipPlan:
    rationale = (
        f"Purchase-focused {product.label} window; "
        f"terms={', '.join(window.matched_terms[:6])}; "
        f"signals={', '.join(window.matched_signals)}; "
        f"product_score={window.product_score}; "
        f"sales_score={window.sales_score}; "
        f"arc_score={window.arc_score}"
    )
    segments = [
        FullSttSegment(
            scene_id=row.scene_id,
            source_start_ms=row.start_ms,
            source_end_ms=row.end_ms,
            rationale=rationale,
        )
        for row in window.rows
    ]
    return FullSttClipPlan(
        segments=segments,
        total_duration_ms=sum(s.duration_ms for s in segments),
        global_rationale=rationale,
        fallback_used=False,
    )


_FALLBACK_PATTERNS: tuple[tuple[float, ...], ...] = (
    (0.1, 0.35, 0.6, 0.85),
    (0.05, 0.2, 0.4, 0.55),
    (0.45, 0.6, 0.75, 0.9),
    (0.15, 0.4, 0.55, 0.8),
    (0.0, 0.3, 0.65, 0.95),
)


def _positional_fallback(
    scenes: list[PurchaseNarrativeScene],
    target_duration_ms: int,
    *,
    positions: tuple[float, ...],
) -> FullSttClipPlan:
    if not scenes:
        return _empty_plan("purchase_planner_no_scenes")
    anchors = sorted(
        max(0, min(len(scenes) - 1, round((len(scenes) - 1) * pos)))
        for pos in positions
    )
    rows: list[PurchaseNarrativeScene] = []
    seen: set[str] = set()
    for idx in anchors:
        scene = scenes[idx]
        if scene.scene_id in seen:
            continue
        rows.append(scene)
        seen.add(scene.scene_id)
        if rows[-1].end_ms - rows[0].start_ms >= target_duration_ms:
            break
    if not rows:
        rows = [scenes[0]]
    segments = [
        FullSttSegment(
            scene_id=row.scene_id,
            source_start_ms=row.start_ms,
            source_end_ms=row.end_ms,
            rationale="purchase_planner_positional_fallback",
        )
        for row in rows
    ]
    return FullSttClipPlan(
        segments=segments,
        total_duration_ms=sum(s.duration_ms for s in segments),
        global_rationale="purchase_planner_positional_fallback",
        fallback_used=True,
    )


def _empty_plan(reason: str) -> FullSttClipPlan:
    return FullSttClipPlan(
        segments=[],
        total_duration_ms=0,
        global_rationale=reason,
        fallback_used=True,
        error=reason,
    )


__all__ = [
    "ProductNarrativeContext",
    "PurchaseNarrativeScene",
    "plan_purchase_focused_shorts",
]
