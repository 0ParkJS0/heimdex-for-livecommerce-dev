"""Overlay-enumeration result dataclasses consumed by overlay_shorts.

These are the pure (no cv2 / no I/O) result rows that the
overlay-driven shorts assembler reads. They previously lived in
``shorts_auto_product.enumerate_overlay.service``, but that package was
moved into the ``product-enumerate-worker`` (overlay enumeration is
worker-side now) and deleted from the API. The shorts-assembly path
(``overlay_shorts``) is OUT OF SCOPE for that migration and still lives
in the API, so the data contract it depends on lives here with it.

The fields mirror the worker / pipelines overlay output shape — the
assembler reads ``OverlayProduct.appearances`` (temporal windows) and
``best_scene_id`` to build the clip windows. When ``overlay_shorts`` is
wired to the worker callback, the API will hydrate these from the
persisted catalog rows.
"""

from __future__ import annotations

from dataclasses import dataclass


# Algorithm version for overlay-source catalog rows. Kept in lockstep
# with ``heimdex_media_pipelines.product_enum.OVERLAY_ENUMERATION_VERSION``.
OVERLAY_ENUMERATION_VERSION = "overlay-v0.1"


@dataclass(frozen=True)
class OverlayAppearance:
    """One keyframe in which a product's overlay was visible."""

    scene_id: str
    timestamp_ms: int
    detector_score: float
    extracted_name: str
    extracted_price: int | None


@dataclass(frozen=True)
class OverlayProduct:
    """A unique product discovered in the video, with all appearances."""

    # Deterministic, derived from the video id and ordinal: f"{video_drive_id}_p{NNN}".
    product_id: str
    # Canonical -- the most frequent name variant after clustering.
    name: str
    price: int | None
    # 'top-left', 'top-center', 'top-right', 'middle-*', 'bottom-*', 'full-frame'.
    position: str
    # Highest-scoring appearance; the picker runs OWLv2 against this frame.
    best_scene_id: str
    # OWLv2-cropped product image. None when the picker found no acceptable bbox.
    image_s3_key: str | None
    appearances: tuple[OverlayAppearance, ...]
    name_variants: tuple[str, ...]


@dataclass(frozen=True)
class DetectorStats:
    n_scenes_seen: int
    n_with_overlay: int
    score_threshold: float


@dataclass(frozen=True)
class ExtractionStats:
    n_called: int
    # Frames the LLM returned an empty products list for -- a natural
    # false-positive filter on top of the classical detector.
    n_empty_products: int
    openai_cost_usd: float


@dataclass(frozen=True)
class PickerStats:
    n_with_bbox: int
    n_without_bbox: int


@dataclass(frozen=True)
class OverlayEnumerationResult:
    video_drive_id: str
    products: tuple[OverlayProduct, ...]
    detector: DetectorStats
    extraction: ExtractionStats
    picker: PickerStats
    enumeration_version: str = OVERLAY_ENUMERATION_VERSION
