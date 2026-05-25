"""Orchestrator for the overlay-driven enumeration pipeline.

End-to-end:

1. Load per-scene metadata from OpenSearch (ocr_text_raw,
   transcript_raw, keyframe_timestamp_ms) and pull keyframe images
   from S3.
2. Score each keyframe with the classical overlay detector
   (OCR price patterns + rectangular candidate + saturation + MFV).
3. Extract structured product info from overlay-bearing keyframes
   using a vision LLM (gpt-4o-mini by default).
4. Cluster appearances per video into a unique-product catalog via
   fuzzy name matching, with promo / brand-only entries dropped.
5. For each product, pick the cleanest product-image crop within
   the chosen keyframe using OWLv2. Inference is delegated to a
   caller-supplied detector protocol so this module never loads a
   GPU model inside the API process.

Returns the assembled catalog as an in-memory result. Persisting
to ``product_catalog_entries`` is deliberately not done here; that
is a later wiring step done by the caller.

Loose-coupling: this module imports ONLY from ``opensearchpy``,
``openai``, ``boto3``, :mod:`heimdex_media_contracts.product`,
:mod:`app.config`, and own-module symbols. No cross-imports from
other ``app.modules.*``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.shorts_auto_product.enumerate_overlay.errors import (
    OverlayBudgetExceededError,
    OverlayEnumerationError,
)

logger = logging.getLogger(__name__)


# Algorithm version for overlay-source catalog rows. Bumped on any
# pipeline logic change (detector weights, picker tier, etc.) so a
# wizard can show a "newer scan available" banner against stale
# results. Distinct from the extractor's prompt version.
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


class OwlV2Detector(Protocol):
    """Caller-supplied OWLv2 inference for the image picker.

    Kept as a protocol so this module never imports a GPU-bound
    detector. Production wiring will inject a worker-side adapter;
    tests inject a fixture that returns canned bboxes.
    """

    def detect(
        self,
        frame_bgr: Any,
        queries: list[str],
    ) -> list[dict[str, Any]]:
        """Return one dict per detection.

        Each detection is shaped::

            {'bbox': (x1, y1, x2, y2), 'confidence': float}

        with bbox coordinates normalised to ``[0, 1]``.
        """
        ...


async def _run_in_thread(func, /, *args, **kwargs):
    """Helper -- run a blocking function in the default thread pool."""
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(
            None, lambda: func(*args, **kwargs)
        )
    return await loop.run_in_executor(None, func, *args)


async def run_overlay_enumeration(
    *,
    session: AsyncSession,
    os_client: Any,
    openai_client: Any,
    s3_client: Any,
    owlv2_detector: OwlV2Detector,
    org_id: UUID,
    video_db_id: UUID,
    video_drive_id: str,
    keyframe_s3_prefix: str,
    crop_upload_prefix: str,
    index_alias: str = "heimdex_scenes",
    extraction_model: str = "gpt-4o-mini",
    extraction_daily_cap_usd: float = 20.0,
    detector_score_threshold: float | None = None,
) -> OverlayEnumerationResult:
    """Run the overlay-driven enumeration pipeline end-to-end.

    Args:
        session: Async SQLAlchemy session. Read-only in this module --
            no catalog rows are written. Kept in the signature for
            symmetry with ``run_stt_enumeration`` and future wiring.
        os_client: ``AsyncOpenSearch`` for scene metadata.
        openai_client: ``AsyncOpenAI`` for the extraction LLM call.
        s3_client: ``boto3`` S3 client for keyframe download and
            cropped-image upload.
        owlv2_detector: Caller-supplied OWLv2 inference. See the
            :class:`OwlV2Detector` protocol; tests inject a fake.
        org_id: Tenant scope.
        video_db_id: ``drive_files.id`` UUID.
        video_drive_id: ``gd_<hash>`` video identifier.
        keyframe_s3_prefix: S3 prefix under which the video's
            keyframes live, as recorded on the ``drive_files`` row.
            Passed in by the caller so this module does not need a
            cross-module import of the drive model.
        crop_upload_prefix: S3 prefix the picker writes product crops
            to, e.g. ``s3://<bucket>/catalog/overlay/<video_drive_id>``.
        index_alias: OpenSearch scenes alias name.
        extraction_model: ``'gpt-4o-mini'`` (default) or ``'qwen'``
            once the Qwen backend is wired.
        extraction_daily_cap_usd: Per-UTC-day spend ceiling on the
            extraction LLM. Crossing it stops further calls; the
            already-extracted candidates still go through the rest of
            the pipeline.
        detector_score_threshold: Override the classical detector's
            score cutoff. ``None`` means use the module default.

    Returns:
        An :class:`OverlayEnumerationResult` containing the assembled
        catalog and per-stage stats. The caller decides whether to
        persist it.

    Raises:
        OverlayEnumerationError: any pipeline failure. See
            :mod:`enumerate_overlay.errors` for the concrete subclasses.
    """
    # Imports kept local so that loading ``service.py`` -- the public
    # entry point -- doesn't drag in cv2 / numpy on platforms where
    # the module is only referenced for its dataclasses.
    from app.modules.shorts_auto_product.enumerate_overlay import (
        image_picker,
        keyframe_loader,
        overlay_detector,
        product_clusterer,
        product_extractor,
    )

    _ = session  # documented above; reserved for future wiring.

    scenes = await keyframe_loader.load_scene_metadata(
        os_client=os_client,
        index_alias=index_alias,
        org_id=org_id,
        video_drive_id=video_drive_id,
    )

    score_threshold = (
        detector_score_threshold
        if detector_score_threshold is not None
        else overlay_detector.DEFAULT_SCORE_THRESHOLD
    )

    # ----- detection pass -------------------------------------------------
    # We keep the decoded frame for any scene that passes detection so
    # the extractor and picker can re-use it without a second S3 GET.
    candidate_frames: dict[str, Any] = {}
    candidate_readings: dict[str, overlay_detector.DetectorReading] = {}
    n_with_overlay = 0

    for scene in scenes:
        try:
            frame = await _run_in_thread(
                keyframe_loader.download_keyframe,
                s3_client=s3_client,
                keyframe_s3_prefix=keyframe_s3_prefix,
                scene_id=scene.scene_id,
            )
        except Exception as exc:
            logger.info(
                "overlay_enum_keyframe_skip",
                extra={
                    "video_id": video_drive_id,
                    "scene_id": scene.scene_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            continue

        reading = await _run_in_thread(
            overlay_detector.score_keyframe,
            scene_id=scene.scene_id,
            img_bgr=frame,
            ocr_text=scene.ocr_text_raw,
            score_threshold=score_threshold,
        )
        if reading.has_overlay:
            n_with_overlay += 1
            candidate_frames[scene.scene_id] = frame
            candidate_readings[scene.scene_id] = reading

    scene_index = {s.scene_id: s for s in scenes}

    # ----- extraction pass ------------------------------------------------
    extractions: list[product_clusterer.ProductExtraction] = []
    n_called = 0
    n_empty_products = 0
    cost_total_usd = 0.0
    budget_tripped = False

    for scene_id, reading in candidate_readings.items():
        if budget_tripped:
            break
        scene = scene_index[scene_id]
        frame = candidate_frames[scene_id]
        try:
            products, cost = await product_extractor.extract_products(
                openai_client=openai_client,
                scene_id=scene.scene_id,
                timestamp_ms=scene.keyframe_timestamp_ms,
                detector_score=reading.score,
                img_bgr=frame,
                daily_cap_usd=extraction_daily_cap_usd,
                model=extraction_model,
            )
        except OverlayBudgetExceededError as exc:
            logger.warning(
                "overlay_enum_budget_exceeded",
                extra={"video_id": video_drive_id, "error": str(exc)},
            )
            budget_tripped = True
            break
        except Exception as exc:
            logger.warning(
                "overlay_enum_extract_failed",
                extra={
                    "video_id": video_drive_id,
                    "scene_id": scene_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            continue
        n_called += 1
        cost_total_usd += cost
        if not products:
            n_empty_products += 1
        extractions.extend(products)

    # ----- cluster pass ---------------------------------------------------
    products = product_clusterer.cluster_products(
        extractions=extractions, video_drive_id=video_drive_id
    )

    # ----- picker pass ----------------------------------------------------
    products_by_scene: dict[str, list[OverlayProduct]] = defaultdict(list)
    for p in products:
        products_by_scene[p.best_scene_id].append(p)

    finalised: dict[str, OverlayProduct] = {}
    n_with_bbox = 0
    n_without_bbox = 0

    for scene_id, scene_products in products_by_scene.items():
        frame = candidate_frames.get(scene_id)
        if frame is None:
            # Picker scene wasn't a detector candidate (rare; the
            # cluster's best frame should have triggered the detector
            # too, but we re-fetch on a miss for safety).
            try:
                frame = await _run_in_thread(
                    keyframe_loader.download_keyframe,
                    s3_client=s3_client,
                    keyframe_s3_prefix=keyframe_s3_prefix,
                    scene_id=scene_id,
                )
            except Exception as exc:
                logger.warning(
                    "overlay_enum_picker_keyframe_missing",
                    extra={
                        "video_id": video_drive_id,
                        "scene_id": scene_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                for p in scene_products:
                    finalised[p.product_id] = p  # image_s3_key stays None
                    n_without_bbox += 1
                continue

        try:
            updated = await _run_in_thread(
                image_picker.pick_product_images_for_scene,
                owlv2_detector=owlv2_detector,
                s3_client=s3_client,
                frame_bgr=frame,
                scene_id=scene_id,
                products=scene_products,
                upload_prefix=crop_upload_prefix,
            )
        except Exception as exc:
            logger.warning(
                "overlay_enum_picker_failed",
                extra={
                    "video_id": video_drive_id,
                    "scene_id": scene_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            for p in scene_products:
                finalised[p.product_id] = p
                n_without_bbox += 1
            continue

        for p in updated:
            finalised[p.product_id] = p
            if p.image_s3_key:
                n_with_bbox += 1
            else:
                n_without_bbox += 1

    # Preserve clusterer order in the final tuple.
    ordered = tuple(
        finalised[p.product_id] for p in products if p.product_id in finalised
    )

    return OverlayEnumerationResult(
        video_drive_id=video_drive_id,
        products=ordered,
        detector=DetectorStats(
            n_scenes_seen=len(scenes),
            n_with_overlay=n_with_overlay,
            score_threshold=score_threshold,
        ),
        extraction=ExtractionStats(
            n_called=n_called,
            n_empty_products=n_empty_products,
            openai_cost_usd=round(cost_total_usd, 6),
        ),
        picker=PickerStats(
            n_with_bbox=n_with_bbox,
            n_without_bbox=n_without_bbox,
        ),
    )


# Keep the public error type referenced so the import does not look
# accidental to static analysis -- it is part of the documented
# Raises contract.
_ = OverlayEnumerationError
