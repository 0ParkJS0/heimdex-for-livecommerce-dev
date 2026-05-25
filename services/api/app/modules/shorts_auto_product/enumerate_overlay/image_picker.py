"""Position-aware OWLv2 picker for product images inside an overlay.

For each ``OverlayProduct`` whose ``best_scene_id`` falls on the given
frame, score every OWLv2 detection by how well it matches the
product's expected on-screen position, then greedily assign the
highest-scoring unclaimed detection to each product. The chosen crop
is uploaded to S3 and the product's ``image_s3_key`` is filled in.

The OWLv2 model itself is provided by the caller via the
:class:`OwlV2Detector` protocol so this module never imports a
GPU-bound dependency.

Algorithm ported from the workspace prototype (tier-3 v4).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import cv2
import numpy as np

from app.modules.shorts_auto_product.enumerate_overlay.service import (
    OverlayProduct,
    OwlV2Detector,
)

logger = logging.getLogger(__name__)


DEFAULT_SCORE_THRESHOLD = 0.13

# Weights for the composite per-detection score. Position dominates --
# the LLM's position label is the strongest signal about which
# detection belongs to which product.
_W_PROMINENCE = 0.20
_W_CONFIDENCE = 0.15
_W_SHARPNESS = 0.10
_W_CENTEREDNESS = 0.45
_W_ASPECT = 0.10

# Detections whose center is further than this from the product's
# target position are excluded outright (score 0). 0.30 is roughly the
# distance between adjacent zone centers.
_POSITION_GATE_DIST = 0.30

# OWLv2 zero-shot queries. Broad enough to catch the package
# silhouettes that show up in livecommerce overlays.
_QUERIES = (
    "product packaging",
    "product photo",
    "product box",
    "product image",
    "bottle",
    "package",
    "container",
)

_POSITION_CENTERS: dict[str, tuple[float, float]] = {
    "top-left":      (0.25, 0.25),
    "top-center":    (0.50, 0.25),
    "top-right":     (0.75, 0.25),
    "middle-left":   (0.25, 0.50),
    "middle-center": (0.50, 0.50),
    "middle-right":  (0.75, 0.50),
    "bottom-left":   (0.25, 0.75),
    "bottom-center": (0.50, 0.75),
    "bottom-right":  (0.75, 0.75),
    "full-frame":    (0.50, 0.50),
}


def _nms_lite(
    detections: list[dict[str, Any]], overlap_thresh: float = 0.70
) -> list[dict[str, Any]]:
    """Drop near-duplicates by sorting on confidence and removing high overlap."""
    detections = sorted(detections, key=lambda d: -d["confidence"])
    kept: list[dict[str, Any]] = []
    for d in detections:
        x1, y1, x2, y2 = d["bbox"]
        a1 = (x2 - x1) * (y2 - y1)
        if a1 <= 0:
            continue
        overlap = False
        for k in kept:
            kx1, ky1, kx2, ky2 = k["bbox"]
            ix1 = max(x1, kx1)
            iy1 = max(y1, ky1)
            ix2 = min(x2, kx2)
            iy2 = min(y2, ky2)
            if ix2 <= ix1 or iy2 <= iy1:
                continue
            inter = (ix2 - ix1) * (iy2 - iy1)
            a2 = (kx2 - kx1) * (ky2 - ky1)
            if inter / min(a1, a2) > overlap_thresh:
                overlap = True
                break
        if not overlap:
            kept.append(d)
    return kept


def _split_target_for_duplicates(
    position: str, n_products: int, idx: int
) -> tuple[float, float]:
    """When ``n_products`` share a position, split the zone vertically.

    e.g. ``"top-center" * 2`` becomes top-of-card / bottom-of-card.
    """
    base = _POSITION_CENTERS.get(position, (0.5, 0.5))
    if n_products <= 1:
        return base
    cx, cy = base
    offset = (idx - (n_products - 1) / 2) * 0.12
    return cx, max(0.05, min(0.95, cy + offset))


def _aspect_score(bbox: tuple[float, float, float, float]) -> float:
    """Penalise very thin / wide bboxes (likely text rows, not products)."""
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    if bw <= 0 or bh <= 0:
        return 0.0
    r = bw / bh
    if r > 1.0:
        r = 1.0 / r
    if r >= 0.5:
        return 1.0
    if r >= 0.3:
        return (r - 0.3) / 0.2
    return 0.0


def _sharpness(crop_bgr: np.ndarray | None) -> float:
    if crop_bgr is None or crop_bgr.size == 0:
        return 0.0
    g = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    return max(
        0.0, min(1.0, float(cv2.Laplacian(g, cv2.CV_64F).var()) / 500.0)
    )


def _crop_normalized(
    frame_bgr: np.ndarray, bbox: tuple[float, float, float, float]
) -> np.ndarray | None:
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = bbox
    ix1, iy1 = max(0, int(x1 * w)), max(0, int(y1 * h))
    ix2, iy2 = min(w, int(x2 * w)), min(h, int(y2 * h))
    if ix2 <= ix1 or iy2 <= iy1:
        return None
    return frame_bgr[iy1:iy2, ix1:ix2]


def _composite(
    det: dict[str, Any],
    frame_bgr: np.ndarray,
    target_pos: tuple[float, float],
) -> float:
    """Score one detection against one product's target position."""
    bbox = det["bbox"]
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    tx, ty = target_pos
    dist = ((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5
    if dist > _POSITION_GATE_DIST:
        return 0.0

    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    prominence = max(0.0, min(1.0, bw * bh * 4))
    confidence = det["confidence"]
    sharpness = _sharpness(_crop_normalized(frame_bgr, bbox))
    aspect = _aspect_score(bbox)
    centeredness = max(0.0, 1.0 - dist / _POSITION_GATE_DIST)

    return (
        _W_PROMINENCE * prominence
        + _W_CONFIDENCE * confidence
        + _W_SHARPNESS * sharpness
        + _W_ASPECT * aspect
        + _W_CENTEREDNESS * centeredness
    )


def _parse_s3_url(url: str) -> tuple[str, str]:
    if not url.startswith("s3://"):
        raise ValueError(f"upload prefix must start with s3://: {url!r}")
    rest = url[len("s3://"):]
    bucket, _, key = rest.partition("/")
    if not bucket:
        raise ValueError(f"upload prefix has no bucket: {url!r}")
    return bucket, key


def _upload_crop(
    *,
    s3_client: Any,
    crop_bgr: np.ndarray,
    upload_prefix: str,
    product_id: str,
    quality: int = 85,
) -> str:
    """Encode the crop as JPEG and PUT it to S3. Returns the object key."""
    ok, buf = cv2.imencode(
        ".jpg", crop_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality]
    )
    if not ok:
        raise RuntimeError("cv2.imencode failed for picker crop")
    bucket, key_prefix = _parse_s3_url(upload_prefix.rstrip("/"))
    object_key = (
        f"{key_prefix}/{product_id}.jpg" if key_prefix else f"{product_id}.jpg"
    )
    s3_client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=buf.tobytes(),
        ContentType="image/jpeg",
    )
    return f"s3://{bucket}/{object_key}"


def pick_product_images_for_scene(
    *,
    owlv2_detector: OwlV2Detector,
    s3_client: Any,
    frame_bgr: np.ndarray,
    scene_id: str,
    products: list[OverlayProduct],
    upload_prefix: str,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> list[OverlayProduct]:
    """Pick + upload product crops for every product anchored on this scene.

    Args:
        owlv2_detector: Caller-supplied inference adapter.
        s3_client: ``boto3`` S3 client used for the crop upload.
        frame_bgr: Decoded keyframe for ``scene_id``.
        scene_id: Identifies the frame -- used to assert ``products``
            actually belong here.
        products: ``OverlayProduct`` rows whose ``best_scene_id`` ==
            ``scene_id``. The function returns one updated copy per
            input, preserving order.
        upload_prefix: ``s3://bucket/key`` under which crops are stored
            as ``{prefix}/{product_id}.jpg``.
        score_threshold: Composite-score cutoff; products with no
            qualifying detection get ``image_s3_key=None``.

    Returns:
        New ``OverlayProduct`` instances with ``image_s3_key`` filled
        in where a usable crop was found.
    """
    raw_dets = owlv2_detector.detect(frame_bgr, list(_QUERIES))
    detections = [
        d for d in raw_dets if d.get("confidence", 0.0) >= score_threshold
    ]
    detections = _nms_lite(detections, overlap_thresh=0.70)

    # Group products by their declared position so we can split when
    # multiple share the same zone label.
    by_position: dict[str, list[OverlayProduct]] = {}
    for p in products:
        by_position.setdefault(p.position, []).append(p)

    targets: dict[str, tuple[float, float]] = {}
    for position, group in by_position.items():
        for idx, p in enumerate(group):
            targets[p.product_id] = _split_target_for_duplicates(
                position, len(group), idx
            )

    # Process products with concrete positions first; full-frame
    # placeholders take whatever is left.
    ordered = sorted(
        products,
        key=lambda p: 0 if p.position != "full-frame" else 1,
    )

    unclaimed = list(detections)
    chosen: dict[str, dict[str, Any] | None] = {}
    for p in ordered:
        target = targets[p.product_id]
        best: dict[str, Any] | None = None
        best_score = 0.0
        for d in unclaimed:
            s = _composite(d, frame_bgr, target)
            if s > best_score:
                best = d
                best_score = s
        chosen[p.product_id] = best
        if best is not None:
            unclaimed.remove(best)

    updated: list[OverlayProduct] = []
    for p in products:
        det = chosen.get(p.product_id)
        image_s3_key: str | None = None
        if det is not None:
            crop = _crop_normalized(frame_bgr, det["bbox"])
            if crop is not None and crop.size:
                try:
                    image_s3_key = _upload_crop(
                        s3_client=s3_client,
                        crop_bgr=crop,
                        upload_prefix=upload_prefix,
                        product_id=p.product_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "overlay_picker_upload_failed",
                        extra={
                            "scene_id": scene_id,
                            "product_id": p.product_id,
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    )
        updated.append(replace(p, image_s3_key=image_s3_key))
    return updated
