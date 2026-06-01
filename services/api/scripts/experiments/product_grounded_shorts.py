"""Local experiment: purchase-centric product shorts from bounded scene windows.

This script is intentionally outside the FastAPI app import path. It lets us
test a product-grounded narrative planner against staging data without changing
the product-enumerate worker or any deployed API route behavior.

Typical staging-container usage:

    python scripts/experiments/product_grounded_shorts.py --enqueue

Default targets are the three videos requested for the experiment. The planner
uses existing catalog rows when available and a manual read-only product context
for gd_75f4fab4913c2bb1, which currently has no catalog rows on staging.

The selection goal is not only "about the selected product". For livecommerce
sources, the chosen window should make a viewer want to buy: product-specific
evidence plus benefits, demonstration/use, price/offer, urgency, CTA, or
objection-handling signals in a contiguous narrative window.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text

import app.db.models  # noqa: F401 - register SQLAlchemy model relationships.
from app.db.base import get_async_session_factory
from app.modules.search.scene_client import SceneSearchClient
from app.modules.shorts_auto_product.track_stt.composition_builder import (
    build_composition_spec_from_full_stt,
)
from app.modules.shorts_auto_product.track_stt.full_stt.types import (
    FullSttClipPlan,
    FullSttSegment,
)
from app.modules.shorts_render.repository import ShortsRenderJobRepository
from app.modules.shorts_render.schemas import RenderJobCreate
from app.modules.shorts_render.service import ShortsRenderService


DEFAULT_USER_ID = UUID("c5d3050e-d787-4ff4-888a-b506c8c76ae5")
DEFAULT_VIDEOS = (
    "gd_7582799e17926a31",
    "gd_75f4fab4913c2bb1",
    "gd_d24cb28631262130",
)

# Existing catalog picks where staging already has a suitable product row.
DEFAULT_CATALOG_BY_VIDEO = {
    "gd_7582799e17926a31": UUID("9957fbd2-dd14-40d4-8d1b-b056bed5557a"),
    "gd_d24cb28631262130": UUID("2e7261ef-5ed2-4f87-a8eb-a9b5b78ef310"),
}

# gd_75 currently has no catalog rows. The product is evident from OCR/captions.
MANUAL_CONTEXT_BY_VIDEO = {
    "gd_75f4fab4913c2bb1": {
        "label": "fwee Smoothie Lip Balm",
        "aliases": [
            "fwee",
            "smoothie lip balm",
            "smoothie",
            "lip balm",
            "\ub9bd\ubc24",
            "\uc2a4\ubb34\ub514",
        ],
    }
}


@dataclass(frozen=True)
class ProductContext:
    label: str
    aliases: list[str]
    catalog_entry_id: UUID | None = None
    first_mention_ms: int | None = None
    example_quote: str | None = None


@dataclass(frozen=True)
class SceneRow:
    scene_id: str
    start_ms: int
    end_ms: int
    transcript: str
    ocr: str
    caption: str

    @property
    def text(self) -> str:
        return " ".join(part for part in (self.transcript, self.ocr, self.caption) if part)


@dataclass(frozen=True)
class ScoredScene:
    scene: SceneRow
    score: float
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class PlannedShort:
    index: int
    title: str
    score: float
    start_ms: int
    end_ms: int
    scenes: list[SceneRow]
    rationale: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class WindowScore:
    rows: list[SceneRow]
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

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


SALES_SIGNAL_PATTERNS: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    (
        "benefit",
        6.0,
        (
            "좋", "예쁘", "편하", "고급", "깔끔", "부드", "촉촉", "가볍", "탄탄",
            "맛있", "아삭", "시원", "신선", "활용", "데일리", "매일", "입기",
            "바르", "보습", "발색", "향", "nice", "soft", "comfortable",
        ),
    ),
    (
        "demo_or_usage",
        7.0,
        (
            "보여", "보이", "착용", "신어", "발라", "먹", "드셔", "열어", "꺼내",
            "넣", "사용", "활용", "코디", "연출", "사이즈", "컬러", "색상",
            "제형", "텍스처", "구성", "use", "wear", "apply", "color",
        ),
    ),
    (
        "specific_feature",
        5.0,
        (
            "소재", "굽", "쿠션", "스트랩", "용량", "10kg", "키로", "포기",
            "국산", "원재료", "케이스", "패키지", "발림", "광택", "밀착",
            "feature", "texture", "package",
        ),
    ),
    (
        "price_or_offer",
        8.0,
        (
            "가격", "할인", "특가", "혜택", "쿠폰", "무료", "배송", "구매",
            "원", "%", "세일", "sale", "discount", "price", "free shipping",
        ),
    ),
    (
        "urgency",
        5.5,
        (
            "지금", "오늘", "이번", "마지막", "한정", "품절", "남았", "라이브",
            "기회", "놓치", "now", "today", "limited",
        ),
    ),
    (
        "cta",
        7.0,
        (
            "구매", "주문", "담아", "클릭", "선택", "가져가", "챙겨", "추천",
            "사세요", "하세요", "buy", "order", "click", "recommend",
        ),
    ),
    (
        "objection_handling",
        4.0,
        (
            "걱정", "부담", "괜찮", "문제", "교환", "반품", "보관", "오래",
            "쉽", "간편", "누구나", "아깝", "비싸", "아니", "concern",
        ),
    ),
)


NARRATIVE_OPENING_TERMS = (
    "오늘", "소개", "보여", "상품", "제품", "이거", "요거", "바로", "먼저",
    "today", "this", "product",
)
NARRATIVE_CLOSE_TERMS = (
    "구매", "주문", "담아", "지금", "오늘", "추천", "가져가", "놓치", "마지막",
    "buy", "order", "now", "recommend",
)


def _terms_for_product(ctx: ProductContext) -> list[str]:
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


def _score_scene(scene: SceneRow, ctx: ProductContext, terms: list[str]) -> ScoredScene:
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

    # Prefer scenes with real narration when available, but do not exclude
    # caption/OCR-only videos like gd_75.
    if scene.transcript:
        score += 1.0

    return ScoredScene(scene=scene, score=score, matched_terms=tuple(sorted(set(matched))))


def _sales_signals_for_text(text: str) -> tuple[float, tuple[str, ...]]:
    folded = text.casefold()
    score = 0.0
    matched: list[str] = []
    for name, weight, patterns in SALES_SIGNAL_PATTERNS:
        hits = sum(1 for pattern in patterns if pattern.casefold() in folded)
        if hits:
            matched.append(name)
            score += weight * min(2, hits)
    return score, tuple(sorted(set(matched)))


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(term.casefold() in folded for term in terms)


def _score_window(
    rows: list[SceneRow],
    product: ProductContext,
    scene_scores: dict[str, ScoredScene],
    target_duration_ms: int,
) -> WindowScore:
    texts = [row.text for row in rows]
    combined_text = " ".join(texts)
    product_scene_scores = [scene_scores[row.scene_id] for row in rows]
    product_score = sum(item.score for item in product_scene_scores)
    product_scenes = [item for item in product_scene_scores if item.score > 0]
    product_density = len(product_scenes) / max(1, len(rows))
    matched_terms = sorted({term for item in product_scene_scores for term in item.matched_terms})

    sales_score = 0.0
    matched_signals: set[str] = set()
    for text in texts:
        score, signals = _sales_signals_for_text(text)
        sales_score += score
        matched_signals.update(signals)

    first_third = " ".join(texts[: max(1, len(texts) // 3)])
    middle_third = " ".join(texts[max(1, len(texts) // 3) : max(2, (len(texts) * 2) // 3)])
    final_third = " ".join(texts[max(1, (len(texts) * 2) // 3) :])

    arc_score = 0.0
    if _contains_any(first_third, NARRATIVE_OPENING_TERMS) or any(
        scene_scores[row.scene_id].score > 0 for row in rows[: max(1, len(rows) // 3)]
    ):
        arc_score += 8.0
    if _contains_any(middle_third, tuple(p for name, _, patterns in SALES_SIGNAL_PATTERNS if name in {"benefit", "demo_or_usage", "specific_feature"} for p in patterns)):
        arc_score += 10.0
    if _contains_any(final_third, NARRATIVE_CLOSE_TERMS):
        arc_score += 8.0
    if {"benefit", "demo_or_usage"} & matched_signals and {"price_or_offer", "cta", "urgency"} & matched_signals:
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

    # Hard product grounding matters most. Windows with only generic selling
    # language score poorly even when they sound persuasive in isolation.
    density_bonus = 25.0 * product_density
    product_presence_bonus = 15.0 if len(product_scenes) >= 2 else 0.0
    score = (
        product_score * 1.4
        + sales_score
        + arc_score
        + density_bonus
        + product_presence_bonus
        - duration_penalty
        - gap_penalty
    )
    if not matched_terms:
        score -= 100.0
    if not matched_signals:
        score -= 25.0
    if product_density < 0.20:
        score -= 20.0

    return WindowScore(
        rows=rows,
        score=round(score, 3),
        product_score=round(product_score, 3),
        sales_score=round(sales_score, 3),
        arc_score=round(arc_score, 3),
        matched_terms=tuple(matched_terms),
        matched_signals=tuple(sorted(matched_signals)),
    )


def _candidate_windows(
    scenes: list[SceneRow],
    *,
    target_duration_ms: int,
    min_duration_ms: int,
    max_duration_ms: int,
) -> list[list[SceneRow]]:
    windows: list[list[SceneRow]] = []
    for start_idx in range(len(scenes)):
        rows: list[SceneRow] = []
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


def plan_shorts(
    *,
    video_id: str,
    product: ProductContext,
    scenes: list[SceneRow],
    requested_count: int,
    target_duration_ms: int,
) -> list[PlannedShort]:
    terms = _terms_for_product(product)
    scene_scores = {scene.scene_id: _score_scene(scene, product, terms) for scene in scenes}
    candidates = _candidate_windows(
        scenes,
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
    windows = [w for w in windows if w.matched_terms and w.matched_signals and w.product_score > 0]
    windows.sort(key=lambda w: (-w.score, w.start_ms))

    planned: list[PlannedShort] = []
    used_ranges: list[tuple[int, int]] = []
    for window in windows:
        start_ms = window.start_ms
        end_ms = window.end_ms
        overlap = any(start_ms < used_end and used_start < end_ms for used_start, used_end in used_ranges)
        if overlap:
            continue
        planned.append(
            PlannedShort(
                index=len(planned) + 1,
                title=f"{product.label} purchase-focused short {len(planned) + 1}",
                score=window.score,
                start_ms=start_ms,
                end_ms=end_ms,
                scenes=window.rows,
                rationale=(
                    f"Purchase-focused {product.label} window; "
                    f"terms={', '.join(window.matched_terms[:6])}; "
                    f"signals={', '.join(window.matched_signals)}; "
                    f"product_score={window.product_score}; "
                    f"sales_score={window.sales_score}; "
                    f"arc_score={window.arc_score}"
                ),
            )
        )
        used_ranges.append((start_ms, end_ms))
        if len(planned) >= requested_count:
            break

    if len(planned) < requested_count:
        raise RuntimeError(
            f"{video_id}: only planned {len(planned)} shorts for {product.label}; "
            f"need {requested_count}"
        )
    return planned


async def _load_video_and_product(session: Any, video_id: str) -> tuple[UUID, str, ProductContext]:
    row = (
        await session.execute(
            text(
                """
                select id, org_id, file_name
                from drive_files
                where video_id=:video_id and is_deleted is false
                """
            ),
            {"video_id": video_id},
        )
    ).mappings().one()
    org_id = row["org_id"]

    catalog_id = DEFAULT_CATALOG_BY_VIDEO.get(video_id)
    if catalog_id is not None:
        cat = (
            await session.execute(
                text(
                    """
                    select id, coalesce(user_label, llm_label) as label, llm_label,
                           spoken_aliases, first_mention_ms, example_quote
                    from product_catalog_entries
                    where id=:id and org_id=:org_id and rejected_at is null
                    """
                ),
                {"id": catalog_id, "org_id": org_id},
            )
        ).mappings().one()
        aliases = list(cat["spoken_aliases"] or [])
        return org_id, row["file_name"], ProductContext(
            label=cat["label"] or cat["llm_label"],
            aliases=aliases,
            catalog_entry_id=cat["id"],
            first_mention_ms=cat["first_mention_ms"],
            example_quote=cat["example_quote"],
        )

    manual = MANUAL_CONTEXT_BY_VIDEO.get(video_id)
    if manual is None:
        raise RuntimeError(f"{video_id}: no default catalog/manual product context")
    return org_id, row["file_name"], ProductContext(
        label=manual["label"],
        aliases=list(manual["aliases"]),
    )


async def _load_scenes(scene_client: SceneSearchClient, org_id: UUID, video_id: str) -> list[SceneRow]:
    response = await scene_client.client.search(
        index=scene_client.alias_name,
        body={
            "size": 5000,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"org_id": str(org_id)}},
                        {"term": {"video_id": video_id}},
                    ]
                }
            },
            "_source": [
                "scene_id",
                "start_ms",
                "end_ms",
                "transcript_raw",
                "ocr_text_raw",
                "scene_caption",
            ],
            "sort": [{"start_ms": "asc"}],
        },
    )
    rows: list[SceneRow] = []
    for hit in response.get("hits", {}).get("hits", []):
        src = hit.get("_source", {}) or {}
        rows.append(
            SceneRow(
                scene_id=str(src.get("scene_id") or ""),
                start_ms=int(src.get("start_ms") or 0),
                end_ms=int(src.get("end_ms") or 0),
                transcript=str(src.get("transcript_raw") or ""),
                ocr=str(src.get("ocr_text_raw") or ""),
                caption=str(src.get("scene_caption") or ""),
            )
        )
    return [r for r in rows if r.scene_id and r.end_ms > r.start_ms]


def _plan_to_full_stt(plan: PlannedShort) -> FullSttClipPlan:
    segments = [
        FullSttSegment(
            scene_id=scene.scene_id,
            source_start_ms=scene.start_ms,
            source_end_ms=scene.end_ms,
            rationale=plan.rationale,
        )
        for scene in plan.scenes
    ]
    return FullSttClipPlan(
        segments=segments,
        total_duration_ms=sum(s.duration_ms for s in segments),
        global_rationale=plan.rationale,
        fallback_used=False,
    )


async def _enqueue_render(
    *,
    session: Any,
    scene_client: SceneSearchClient,
    org_id: UUID,
    user_id: UUID,
    video_id: str,
    plan: PlannedShort,
) -> Any:
    repo = ShortsRenderJobRepository(session)
    service = ShortsRenderService(repository=repo, scene_search=scene_client)
    composition = build_composition_spec_from_full_stt(
        plan=_plan_to_full_stt(plan),
        os_video_id=video_id,
        title=plan.title,
    )
    return await service.create_render_job(
        org_id=org_id,
        user_id=user_id,
        payload=RenderJobCreate(
            video_id=video_id,
            title=plan.title,
            composition=composition,
        ),
        dedupe_within_seconds=0,
        idempotency_key=f"product-grounded:{video_id}:{plan.index}:{plan.start_ms}:{plan.end_ms}",
    )


async def run(args: argparse.Namespace) -> None:
    session_factory = get_async_session_factory()
    scene_client = SceneSearchClient()
    outputs: list[dict[str, Any]] = []
    try:
        async with session_factory() as session:
            for video_id in args.videos:
                org_id, file_name, product = await _load_video_and_product(session, video_id)
                scenes = await _load_scenes(scene_client, org_id, video_id)
                plans = plan_shorts(
                    video_id=video_id,
                    product=product,
                    scenes=scenes,
                    requested_count=args.count,
                    target_duration_ms=args.target_duration_ms,
                )
                for plan in plans:
                    row: dict[str, Any] = {
                        "video_id": video_id,
                        "file_name": file_name,
                        "product": product.label,
                        "catalog_entry_id": str(product.catalog_entry_id) if product.catalog_entry_id else None,
                        "short_index": plan.index,
                        "start_ms": plan.start_ms,
                        "end_ms": plan.end_ms,
                        "duration_ms": plan.duration_ms,
                        "score": plan.score,
                        "scene_ids": [s.scene_id for s in plan.scenes],
                        "rationale": plan.rationale,
                    }
                    if args.enqueue:
                        render = await _enqueue_render(
                            session=session,
                            scene_client=scene_client,
                            org_id=org_id,
                            user_id=args.user_id,
                            video_id=video_id,
                            plan=plan,
                        )
                        row["render_job_id"] = str(render.id)
                        row["render_status"] = render.status
                    outputs.append(row)
            if not args.enqueue:
                await session.rollback()
    finally:
        await scene_client.close()
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--videos", nargs="+", default=list(DEFAULT_VIDEOS))
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--target-duration-ms", type=int, default=60_000)
    parser.add_argument("--user-id", type=UUID, default=DEFAULT_USER_ID)
    parser.add_argument("--enqueue", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
