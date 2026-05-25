"""Unit-scope tests for the overlay-driven enumeration pipeline.

Covers the pure-logic stages -- detector, clusterer, picker. The
extractor and orchestrator wrap external IO (OpenAI, S3, OpenSearch)
and would need a heavier fixture stack; they are exercised end-to-end
in the workspace and intentionally not unit-tested here.

Run locally:

    cd services/api && source .venv/bin/activate && pytest \\
        tests/test_shorts_auto_product_enumerate_overlay.py
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

# The overlay enumeration modules import cv2 (opencv), which is NOT a declared
# API dependency — the overlay feature is dormant and slated to move into a
# dedicated worker (see .claude/plans). Skip the module cleanly when cv2 is
# absent so a bare `pytest` run / the shadow core lane doesn't error on collection.
pytest.importorskip("cv2")

from app.modules.shorts_auto_product.enumerate_overlay.image_picker import (
    pick_product_images_for_scene,
)
from app.modules.shorts_auto_product.enumerate_overlay.overlay_detector import (
    score_keyframe,
)
from app.modules.shorts_auto_product.enumerate_overlay.product_clusterer import (
    DEFAULT_SIMILARITY,
    ProductExtraction,
    cluster_products,
)
from app.modules.shorts_auto_product.enumerate_overlay.service import (
    OverlayProduct,
)


# ---------------------------------------------------------------------------
# Detector


def _plain_frame(h: int = 200, w: int = 360, value: int = 120) -> np.ndarray:
    """Solid-color BGR frame -- no edges, no rectangles."""
    return np.full((h, w, 3), value, dtype=np.uint8)


def test_detector_empty_signals_returns_false():
    img = _plain_frame()
    reading = score_keyframe(scene_id="s1", img_bgr=img, ocr_text="")
    assert reading.has_overlay is False
    assert reading.signals["ocr_price"] == 0.0
    assert reading.signals["ocr_text_density"] == 0.0


def test_detector_price_token_fires_price_signal():
    img = _plain_frame()
    reading = score_keyframe(
        scene_id="s2",
        img_bgr=img,
        ocr_text="센트룸 우먼 더블업 60정 29,900원",
    )
    assert reading.signals["ocr_price"] == 1.0


def test_detector_promo_penalty_with_price_zeroes_verdict():
    img = _plain_frame()
    reading = score_keyframe(
        scene_id="s3",
        img_bgr=img,
        ocr_text="쇬폰 10,000원 적립",
    )
    assert reading.signals["promo_penalty"] >= 1.0
    # Promo penalty has weight -0.5; even with a price signal the
    # combined score should be negative or sub-threshold.
    assert reading.has_overlay is False


def test_detector_structural_gate_blocks_low_signal_pass():
    img = _plain_frame()
    # No price token, no rectangle (solid frame) -- even if the
    # density / saturation signals fired we'd still fail the gate.
    reading = score_keyframe(
        scene_id="s4",
        img_bgr=img,
        ocr_text="x" * 1000,  # huge text but no price token
    )
    assert reading.has_overlay is False


# ---------------------------------------------------------------------------
# Clusterer


def _extraction(
    scene_id: str,
    name: str,
    *,
    price: int | None = None,
    ts: int = 0,
    score: float = 0.5,
    position: str | None = None,
) -> ProductExtraction:
    return ProductExtraction(
        scene_id=scene_id,
        timestamp_ms=ts,
        detector_score=score,
        extracted_name=name,
        extracted_price=price,
        position=position,
    )


def test_clusterer_drops_promo_keywords():
    products = cluster_products(
        extractions=[
            _extraction("s1", "쇬폰 5,000원"),
            _extraction("s2", "사은품 증정"),
        ],
        video_drive_id="gd_test",
    )
    assert products == []


def test_clusterer_drops_bare_brand_names():
    products = cluster_products(
        extractions=[
            _extraction("s1", "센트룸"),
            _extraction("s2", "Osulloc"),
        ],
        video_drive_id="gd_test",
    )
    assert products == []


def test_clusterer_groups_similar_names():
    products = cluster_products(
        extractions=[
            _extraction("s1", "센트룸 우먼 더블업 60정 x 3개", price=69000, ts=1000),
            _extraction("s2", "센트룸 우먼 더블업 60정", price=69000, ts=2000),
            _extraction("s3", "센트룸 우먼 더블업 60정 [90일분]", price=69000, ts=3000),
        ],
        video_drive_id="gd_test",
    )
    assert len(products) == 1
    p = products[0]
    assert p.product_id == "gd_test_p001"
    assert p.price == 69000
    assert len(p.appearances) == 3
    # name_variants preserves insertion order.
    assert len(p.name_variants) == 3


def test_clusterer_keeps_distinct_products():
    products = cluster_products(
        extractions=[
            _extraction("s1", "센트룸 우먼 더블업 60정", price=69000, ts=1000),
            _extraction("s2", "헤라 마크공", price=45000, ts=2000),
        ],
        video_drive_id="gd_test",
        similarity=DEFAULT_SIMILARITY,
    )
    assert len(products) == 2
    # Sorted by first appearance.
    assert products[0].appearances[0].timestamp_ms == 1000
    assert products[1].appearances[0].timestamp_ms == 2000


def test_clusterer_picks_best_scene_by_score():
    products = cluster_products(
        extractions=[
            _extraction("low", "센트룸 우먼 더블업", score=0.42),
            _extraction("high", "센트룸 우먼 더블업", score=0.88),
        ],
        video_drive_id="gd_test",
    )
    assert len(products) == 1
    assert products[0].best_scene_id == "high"


# ---------------------------------------------------------------------------
# Picker


class _FakeOwlV2:
    def __init__(self, dets: list[dict[str, Any]]):
        self._dets = dets

    def detect(self, frame_bgr: Any, queries: list[str]) -> list[dict[str, Any]]:
        return list(self._dets)


class _FakeS3:
    def __init__(self):
        self.put_calls: list[tuple[str, str, int]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str):
        self.put_calls.append((Bucket, Key, len(Body)))
        return {"ETag": "fake"}


def _product(pid: str, *, position: str = "top-left", scene_id: str = "s_pick") -> OverlayProduct:
    return OverlayProduct(
        product_id=pid,
        name=f"product {pid}",
        price=None,
        position=position,
        best_scene_id=scene_id,
        image_s3_key=None,
        appearances=(),
        name_variants=(),
    )


def test_picker_no_detections_yields_no_image():
    s3 = _FakeS3()
    out = pick_product_images_for_scene(
        owlv2_detector=_FakeOwlV2([]),
        s3_client=s3,
        frame_bgr=_plain_frame(200, 200),
        scene_id="s_pick",
        products=[_product("p001")],
        upload_prefix="s3://bucket/key",
    )
    assert out[0].image_s3_key is None
    assert s3.put_calls == []


def test_picker_assigns_detection_in_zone():
    # top-left zone center is (0.25, 0.25). A detection centered there
    # should win for a top-left product.
    s3 = _FakeS3()
    dets = [
        {"bbox": (0.15, 0.15, 0.35, 0.35), "confidence": 0.7},
    ]
    out = pick_product_images_for_scene(
        owlv2_detector=_FakeOwlV2(dets),
        s3_client=s3,
        frame_bgr=_plain_frame(200, 200),
        scene_id="s_pick",
        products=[_product("p001", position="top-left")],
        upload_prefix="s3://bucket/key",
    )
    assert out[0].image_s3_key == "s3://bucket/key/p001.jpg"
    assert s3.put_calls == [("bucket", "key/p001.jpg", s3.put_calls[0][2])]


def test_picker_distance_gate_blocks_far_detection():
    # top-left product (0.25, 0.25) vs detection at bottom-right (0.85, 0.85).
    # Distance >> POSITION_GATE_DIST = 0.30.
    s3 = _FakeS3()
    dets = [
        {"bbox": (0.80, 0.80, 0.95, 0.95), "confidence": 0.9},
    ]
    out = pick_product_images_for_scene(
        owlv2_detector=_FakeOwlV2(dets),
        s3_client=s3,
        frame_bgr=_plain_frame(200, 200),
        scene_id="s_pick",
        products=[_product("p001", position="top-left")],
        upload_prefix="s3://bucket/key",
    )
    assert out[0].image_s3_key is None


def test_picker_splits_same_position_for_two_products():
    # Two top-center products: zone splits vertically (0.50, 0.13)
    # and (0.50, 0.37). Each should claim its own detection.
    s3 = _FakeS3()
    dets = [
        {"bbox": (0.40, 0.05, 0.60, 0.20), "confidence": 0.7},  # near 0.50, 0.13
        {"bbox": (0.40, 0.30, 0.60, 0.45), "confidence": 0.7},  # near 0.50, 0.37
    ]
    out = pick_product_images_for_scene(
        owlv2_detector=_FakeOwlV2(dets),
        s3_client=s3,
        frame_bgr=_plain_frame(200, 200),
        scene_id="s_pick",
        products=[
            _product("p001", position="top-center"),
            _product("p002", position="top-center"),
        ],
        upload_prefix="s3://bucket/key",
    )
    keys = [p.image_s3_key for p in out]
    assert all(k is not None for k in keys)
    assert keys[0] != keys[1]
    assert len(s3.put_calls) == 2


@pytest.mark.parametrize(
    "url",
    ["", "no-scheme/key", "s3://", "http://bucket/key"],
)
def test_picker_rejects_invalid_upload_prefix(url):
    s3 = _FakeS3()
    dets = [{"bbox": (0.20, 0.20, 0.30, 0.30), "confidence": 0.7}]
    with pytest.raises(ValueError):
        pick_product_images_for_scene(
            owlv2_detector=_FakeOwlV2(dets),
            s3_client=s3,
            frame_bgr=_plain_frame(200, 200),
            scene_id="s_pick",
            products=[_product("p001", position="top-left")],
            upload_prefix=url,
        )
