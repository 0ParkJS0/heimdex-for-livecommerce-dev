from __future__ import annotations

from app.modules.shorts_auto_product.track_stt.purchase_planner import (
    ProductNarrativeContext,
    PurchaseNarrativeScene,
    plan_purchase_focused_shorts,
)


def _scene(idx: int, text: str) -> PurchaseNarrativeScene:
    return PurchaseNarrativeScene(
        scene_id=f"gd_test_scene_{idx:03d}",
        start_ms=idx * 15_000,
        end_ms=(idx + 1) * 15_000,
        transcript=text,
    )


def test_prefers_product_specific_purchase_window_over_generic_sales_window():
    scenes = [
        _scene(0, "오늘 라이브 특가 구매 혜택 지금 주문하세요"),
        _scene(1, "할인 가격 무료 배송 쿠폰 마지막 기회입니다"),
        _scene(2, "슬링백 뮬 보여드릴게요 착용하면 편하고 예쁜 신발입니다"),
        _scene(3, "슬링백 뮬 쿠션과 스트랩이 탄탄하고 데일리로 신기 좋아요"),
        _scene(4, "지금 슬링백 뮬 구매하시면 오늘 특가 혜택으로 가져가세요"),
        _scene(5, "다음 상품으로 넘어가겠습니다"),
    ]

    plans = plan_purchase_focused_shorts(
        scenes=scenes,
        product=ProductNarrativeContext(label="슬링백 뮬", aliases=("슬링백", "신발")),
        target_duration_ms=45_000,
        n=1,
    )

    assert len(plans) == 1
    assert plans[0].fallback_used is False
    scene_ids = [s.scene_id for s in plans[0].segments]
    assert scene_ids == [
        "gd_test_scene_002",
        "gd_test_scene_003",
        "gd_test_scene_004",
    ]
    assert "signals=" in plans[0].global_rationale


def test_ocr_and_caption_can_ground_product_when_transcript_is_empty():
    scenes = [
        PurchaseNarrativeScene(
            scene_id="gd_test_scene_000",
            start_ms=0,
            end_ms=15_000,
            ocr="fwee Smoothie Lip Balm package",
            caption="host applies lip balm color texture",
        ),
        PurchaseNarrativeScene(
            scene_id="gd_test_scene_001",
            start_ms=15_000,
            end_ms=30_000,
            ocr="Smoothie Lip Balm color chart",
            caption="demo of soft lip balm application",
        ),
        PurchaseNarrativeScene(
            scene_id="gd_test_scene_002",
            start_ms=30_000,
            end_ms=45_000,
            ocr="fwee limited sale",
            caption="product package and color benefit",
        ),
    ]

    plans = plan_purchase_focused_shorts(
        scenes=scenes,
        product=ProductNarrativeContext(
            label="fwee Smoothie Lip Balm",
            aliases=("fwee", "Smoothie", "Lip Balm"),
        ),
        target_duration_ms=45_000,
        n=1,
    )

    assert plans[0].fallback_used is False
    assert [s.scene_id for s in plans[0].segments] == [
        "gd_test_scene_000",
        "gd_test_scene_001",
        "gd_test_scene_002",
    ]


def test_returns_distinct_fallbacks_when_no_purchase_window_exists():
    scenes = [
        _scene(i, "일반 대화입니다")
        for i in range(8)
    ]

    plans = plan_purchase_focused_shorts(
        scenes=scenes,
        product=ProductNarrativeContext(label="슬링백 뮬", aliases=("슬링백",)),
        target_duration_ms=45_000,
        n=2,
    )

    assert len(plans) == 2
    assert all(plan.fallback_used for plan in plans)
    assert [s.scene_id for s in plans[0].segments] != [
        s.scene_id for s in plans[1].segments
    ]
