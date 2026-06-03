from __future__ import annotations

from app.modules.shorts_auto_product.track_stt.purchase_planner import (
    ProductNarrativeContext,
    PurchaseNarrativeScene,
)
from app.modules.shorts_auto_product.track_stt.purchase_story_planner import (
    plan_purchase_story_shorts,
)


def _scene(idx: int, text: str) -> PurchaseNarrativeScene:
    return PurchaseNarrativeScene(
        scene_id=f"gd_story_scene_{idx:03d}",
        start_ms=idx * 15_000,
        end_ms=(idx + 1) * 15_000,
        transcript=text,
    )


def test_story_planner_assembles_non_contiguous_product_story_without_price_requirement():
    scenes = [
        _scene(0, "슬링백 뮬 오늘 보여드릴게요 착용하면 라인이 예뻐요"),
        _scene(1, "다른 상품 사은품 선물 이벤트 이야기는 제외되어야 합니다"),
        _scene(2, "슬링백 뮬은 쿠션이 탄탄해서 오래 신어도 편합니다"),
        _scene(3, "다음 컬러 이야기를 잠깐 하고 있습니다"),
        _scene(4, "슬링백 뮬 데일리 코디에 잘 어울려서 추천드려요"),
    ]

    plans = plan_purchase_story_shorts(
        scenes=scenes,
        product=ProductNarrativeContext(label="슬링백 뮬", aliases=("슬링백", "신발")),
        target_duration_ms=45_000,
        n=1,
        min_combo_score=80.0,
    )

    assert len(plans) == 1
    assert plans[0].fallback_used is False
    assert [segment.scene_id for segment in plans[0].segments] == [
        "gd_story_scene_000",
        "gd_story_scene_002",
        "gd_story_scene_004",
    ]
    assert "Story purchase plan" in plans[0].global_rationale
    assert "price" not in plans[0].global_rationale.casefold()


def test_story_planner_rejects_giveaway_sample_and_review_reward_language():
    scenes = [
        _scene(0, "키클레오 프라임 사은품 선물 증정 이벤트 드려요"),
        _scene(1, "키클레오 프라임 구매 인증 포토 리뷰 작성하면 뽑아드립니다"),
        _scene(2, "키클레오 프라임 샘플도 보내드리는 소통왕 혜택입니다"),
        _scene(3, "다음 상품으로 넘어갑니다"),
    ]

    plans = plan_purchase_story_shorts(
        scenes=scenes,
        product=ProductNarrativeContext(label="키클레오 프라임", aliases=("키클레오",)),
        target_duration_ms=45_000,
        n=1,
        min_combo_score=20.0,
    )

    assert plans == []


def test_story_planner_penalizes_competing_catalog_terms():
    scenes = [
        _scene(0, "후드티 오늘 보여드릴게요 기본으로 입기 좋아요"),
        _scene(1, "후드티 지퍼와 원단이 탄탄해서 데일리로 편합니다"),
        _scene(2, "후드티 추천드려요 지금 같이 가져가시면 좋아요"),
        _scene(3, "가디건도 같이 보여드리고 가디건 가격도 좋습니다"),
    ]

    plans = plan_purchase_story_shorts(
        scenes=scenes,
        product=ProductNarrativeContext(label="후드티", aliases=("후드",)),
        sibling_products=[
            ProductNarrativeContext(label="가디건", aliases=("니트 가디건",)),
        ],
        target_duration_ms=45_000,
        n=1,
        min_combo_score=60.0,
    )

    assert len(plans) == 1
    assert "gd_story_scene_003" not in [segment.scene_id for segment in plans[0].segments]


def test_story_planner_returns_distinct_non_overlapping_plans_when_available():
    scenes = [
        _scene(0, "립밤 오늘 보여드릴게요 컬러가 예뻐요"),
        _scene(1, "립밤 발림이 부드럽고 촉촉합니다"),
        _scene(2, "립밤 추천드려요 데일리로 쓰기 좋아요"),
        _scene(3, "잡담입니다"),
        _scene(4, "립밤 두 번째 컬러 보여드릴게요"),
        _scene(5, "립밤 텍스처가 가볍고 보습감이 좋아요"),
        _scene(6, "립밤 하나쯤 가져가시면 활용하기 좋아요"),
    ]

    plans = plan_purchase_story_shorts(
        scenes=scenes,
        product=ProductNarrativeContext(label="립밤", aliases=("컬러 립밤",)),
        target_duration_ms=45_000,
        n=2,
        min_combo_score=40.0,
    )

    assert len(plans) == 2
    first_ids = {segment.scene_id for segment in plans[0].segments}
    second_ids = {segment.scene_id for segment in plans[1].segments}
    assert first_ids.isdisjoint(second_ids)


def test_story_planner_uses_visual_text_for_product_grounding():
    scenes = [
        PurchaseNarrativeScene(
            scene_id="gd_story_scene_000",
            start_ms=0,
            end_ms=15_000,
            transcript="오늘 제품 보여드릴게요",
            ocr="fwee Smoothie Lip Balm",
            caption="host applies lip balm color texture",
        ),
        PurchaseNarrativeScene(
            scene_id="gd_story_scene_001",
            start_ms=15_000,
            end_ms=30_000,
            transcript="발림이 부드럽고 촉촉합니다",
            ocr="Smoothie Lip Balm color chart",
            caption="demo of lip balm application",
        ),
        PurchaseNarrativeScene(
            scene_id="gd_story_scene_002",
            start_ms=30_000,
            end_ms=45_000,
            transcript="추천드려요",
            ocr="fwee",
            caption="product package",
        ),
    ]

    plans = plan_purchase_story_shorts(
        scenes=scenes,
        product=ProductNarrativeContext(
            label="fwee Smoothie Lip Balm",
            aliases=("fwee", "Smoothie", "Lip Balm"),
        ),
        target_duration_ms=45_000,
        n=1,
        min_combo_score=40.0,
    )

    assert len(plans) == 1
    assert [segment.scene_id for segment in plans[0].segments] == [
        "gd_story_scene_000",
        "gd_story_scene_001",
        "gd_story_scene_002",
    ]
