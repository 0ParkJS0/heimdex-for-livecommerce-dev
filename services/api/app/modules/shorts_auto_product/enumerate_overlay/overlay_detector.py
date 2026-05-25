"""Classical overlay detector -- no LLM, no GPU.

Combines cheap signals from each keyframe and the scene's
``ocr_text_raw`` (already produced by the existing OCR worker) into a
weighted score. Frames whose score exceeds the threshold AND pass a
structural gate are flagged ``has_overlay=True``.

Signal sources:

* ``ocr_price``       -- regex match for KRW price / percent-discount
  patterns in the OCR text.
* ``ocr_text_density``-- proxy for how much text is on the frame; long
  text strings indicate a graphic card.
* ``promo_penalty``   -- coupon / event keywords that flip a "card-like"
  frame into a promo banner false-positive.
* ``rect``            -- cv2 contour detection of card-shaped regions.
* ``saturation``      -- HSV saturation ratio; web brand colors saturate.
* ``solid_bg``        -- fraction of the frame in uniform-color regions.
* ``palette``         -- number of quantised colors; graphics use few.

This is a simplified port of the workspace prototype's
``15_classical_detector.py`` adapted for two production constraints:

1. OCR is not re-run; the scene's already-indexed ``ocr_text_raw`` is
   used as a single concatenated string. Signals that needed per-block
   bboxes (``text_align``) are dropped.
2. Multi-frame variance (``mfv``) is also dropped here because it
   requires reading the source video file. A follow-up may inject an
   MFV score per scene through ``mfv_lookup`` when worker-side
   pre-computation is wired.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configurable parameters.

# Final score must exceed this AND a structural gate must fire.
DEFAULT_SCORE_THRESHOLD = 0.40

# Downscale large keyframes for CV speed. The signals are scale-tolerant.
_TARGET_WIDTH = 960

# Edge detection thresholds for rectangle finding.
_EDGE_LOW = 40
_EDGE_HIGH = 120

# Minimum / maximum area for a contour to qualify as an overlay rectangle.
_RECT_MIN_AREA_PCT = 0.03
_RECT_MAX_AREA_PCT = 1.0
_RECT_MIN_RECT_FILL = 0.5

_WEIGHTS: dict[str, float] = {
    "ocr_price": 0.30,
    "ocr_text_density": 0.10,
    "rect": 0.15,
    "saturation": 0.05,
    "solid_bg": 0.15,
    "palette": 0.15,
    "promo_penalty": -0.50,
}

# Regexes for KRW price strings the LLM tends to render in overlays.
# These exclude bare numbers because hosts read out arbitrary numbers
# all the time; we only count typographic price tokens.
_PRICE_PATTERNS = (
    re.compile(r"\d{1,3}(?:,\d{3})+\s*원"),
    re.compile(r"₩\s*\d"),  # KRW sign + digit
    re.compile(r"(?<![\d,.])\d{1,2}\s*%(?:\s|$|\b)"),
    re.compile(r"(?<![\d,])\d{3,5}\s*원"),
)

# When OCR text is dominated by these tokens the frame is a coupon /
# event banner, not a product card.
_PROMO_WORDS = (
    "쇬폰",    # coupon
    "추첨",    # raffle
    "포인트",   # points
    "적립",    # rewards
    "응모",    # entry
    "사은품", # gift
    "배달의",  # delivery prefix
    "라이브 only",
    "live only",
    "전상품",  # all products
)


@dataclass(frozen=True)
class DetectorReading:
    """Output for a single scene."""

    scene_id: str
    has_overlay: bool
    score: float
    # Per-signal sub-scores in ``[0, 1]`` for offline analysis / threshold
    # tuning; not consumed by downstream stages.
    signals: dict[str, float]


# ---------------------------------------------------------------------------
# Per-signal scorers.

def _signal_ocr_price(text: str) -> float:
    for pat in _PRICE_PATTERNS:
        if pat.search(text):
            return 1.0
    return 0.0


def _signal_ocr_text_density(text: str) -> float:
    # Proxy for how much typographic content sits on the frame. Tuned
    # so a ~200-char graphic card saturates the signal.
    n = len(text)
    return min(n / 200.0, 1.0)


def _signal_promo_penalty(text: str) -> float:
    if not text:
        return 0.0
    lowered = text.lower()
    hits = sum(1 for w in _PROMO_WORDS if w.lower() in lowered)
    if hits == 0:
        return 0.0
    # Heuristic: a single promo keyword next to a price is a coupon
    # banner; treat as full penalty.
    if hits >= 1 and bool(re.search(r"\d", text)):
        return 1.0
    return min(hits / 3.0, 1.0)


def _downscale(img_bgr: np.ndarray) -> np.ndarray:
    h, w = img_bgr.shape[:2]
    if w <= _TARGET_WIDTH:
        return img_bgr
    scale = _TARGET_WIDTH / w
    return cv2.resize(img_bgr, (_TARGET_WIDTH, int(h * scale)))


def _signal_rect(img_bgr: np.ndarray) -> float:
    h, w = img_bgr.shape[:2]
    frame_area = h * w
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, _EDGE_LOW, _EDGE_HIGH)
    edges = cv2.morphologyEx(
        edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)
    )
    contours, _ = cv2.findContours(
        edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    n_rects = 0
    for c in contours:
        area = float(cv2.contourArea(c))
        if area < frame_area * _RECT_MIN_AREA_PCT:
            continue
        if area > frame_area * _RECT_MAX_AREA_PCT:
            continue
        _, _, ww, hh = cv2.boundingRect(c)
        bbox_area = ww * hh
        if bbox_area == 0:
            continue
        if area / bbox_area < _RECT_MIN_RECT_FILL:
            continue
        n_rects += 1
    return min(n_rects / 3.0, 1.0)


def _signal_saturation(img_bgr: np.ndarray) -> float:
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    high = float((hsv[:, :, 1] > 140).mean())
    return min(high * 3.0, 1.0)


def _signal_solid_bg(img_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    k = 25
    mean = cv2.boxFilter(gray, ddepth=-1, ksize=(k, k))
    mean_sq = cv2.boxFilter(gray * gray, ddepth=-1, ksize=(k, k))
    local_var = np.maximum(mean_sq - mean * mean, 0)
    local_std = np.sqrt(local_var)
    solid = float((local_std < 6).mean())
    return min(max((solid - 0.20) / 0.40, 0.0), 1.0)


def _signal_palette(img_bgr: np.ndarray) -> float:
    small = cv2.resize(img_bgr, (200, 112))
    q = (small // 16).astype(np.uint8)
    codes = (
        (q[..., 0].astype(np.int32) << 16)
        | (q[..., 1].astype(np.int32) << 8)
        | q[..., 2].astype(np.int32)
    )
    n_colors = int(len(np.unique(codes)))
    if n_colors < 100:
        return 1.0
    if n_colors < 300:
        return 0.7
    if n_colors < 600:
        return 0.3
    return 0.0


# ---------------------------------------------------------------------------
# Combiner.

def score_keyframe(
    *,
    scene_id: str,
    img_bgr: np.ndarray,
    ocr_text: str,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> DetectorReading:
    """Run all signals and combine into a single overlay verdict.

    Args:
        scene_id: Echoed back in the reading for upstream joins.
        img_bgr: Decoded keyframe, BGR uint8.
        ocr_text: Concatenated OCR string from the scene's
            ``ocr_text_raw`` field.
        score_threshold: Minimum weighted score required, in addition
            to a structural gate (price OR rectangle signal must be
            at least 0.5).

    Returns:
        :class:`DetectorReading` with the boolean verdict, the
        combined score, and per-signal sub-scores.
    """
    img_small = _downscale(img_bgr)

    signals: dict[str, float] = {
        "ocr_price": _signal_ocr_price(ocr_text),
        "ocr_text_density": _signal_ocr_text_density(ocr_text),
        "promo_penalty": _signal_promo_penalty(ocr_text),
        "rect": _signal_rect(img_small),
        "saturation": _signal_saturation(img_small),
        "solid_bg": _signal_solid_bg(img_small),
        "palette": _signal_palette(img_small),
    }
    score = round(
        sum(_WEIGHTS[k] * v for k, v in signals.items() if k in _WEIGHTS),
        3,
    )
    # Structural gate -- score alone is not enough; we want at least
    # one positive overlay marker (price text or a rectangle contour).
    gate = signals["ocr_price"] >= 0.5 or signals["rect"] >= 0.5
    has_overlay = (score >= score_threshold) and gate
    return DetectorReading(
        scene_id=scene_id,
        has_overlay=has_overlay,
        score=score,
        signals=signals,
    )
