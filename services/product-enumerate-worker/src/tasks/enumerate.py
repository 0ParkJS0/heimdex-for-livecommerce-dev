"""Per-job handler for ``product.enumerate_job`` messages.

Flow (per plan §6.1, mirrored in
``heimdex_media_pipelines.product_enum.pipeline.enumerate_products``):

    1. Claim the job → API marks ``stage=enumerating``, returns
       ``(org_id, video_id, duration_preset_sec)``.
    2. Heartbeat ``progress_pct=10`` while we resolve the scene list.
    3. Resolve scene metadata via the Phase 2.5a internal endpoint +
       download keyframes from S3.
    4. Heartbeat ``progress_pct=30`` while we run the LLM batches.
    5. Run :func:`enumerate_products` (LLM + SigLIP2 + cluster + filter).
    6. Upload canonical crops to
       ``s3://{bucket}/products/{org_id}/{video_id}/{uuid}.jpg``.
    7. POST ``/internal/products/{job_id}/complete`` with the catalog
       entry payload + accumulated cost.

Failures are caught at the dispatcher boundary; this module raises so
the dispatcher can map exceptions to the right ``error_code``.
"""

from __future__ import annotations

import io
import logging
import uuid as _uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
from heimdex_media_contracts.product import ProductEnumerateJob
from heimdex_media_pipelines.product_enum import (
    OVERLAY_ENUMERATION_VERSION,
    CanonicalProduct,
    EnumerationConfig,
    EnumerationProgressEvent,
    OverlayKeyframe,
    ProgressCallback,
    SceneKeyframe,
    enumerate_products,
    enumerate_products_overlay,
    ocr_nonempty_ratio,
    should_use_ocr_blind_fallback,
)
from heimdex_media_pipelines.siglip2 import (
    SiglipConfig,
    embed_pil_image_batch,
)
from heimdex_media_pipelines.siglip2 import (
    load as load_siglip,
)
from heimdex_worker_sdk.s3 import S3Client

from src.api_client import ApiClient
from src.openai_vlm import OpenAIVlmClient, VlmSchemaError, VlmTimeoutError
from src.overlay_extractor import OverlayProductExtractor
from src.overlay_owlv2_adapter import WorkerOwlV2Detector
from src.product_merge import merge_products_by_label
from src.settings import WorkerSettings

if TYPE_CHECKING:  # pragma: no cover
    from PIL import Image

logger = logging.getLogger(__name__)


# Source tag for the catalog payload's ``enumeration_source`` field.
_SOURCE_VISION = "vision"
_SOURCE_OVERLAY = "overlay"

# Modes that run the overlay pass. ``vision+overlay`` runs both passes
# in one invocation (shared keyframe fetch + loaded models); ``overlay``
# runs only the overlay pass; ``vision`` (default) is the legacy path.
_MODES_WITH_OVERLAY = frozenset({"vision+overlay", "overlay"})
_MODES_WITH_VISION = frozenset({"vision", "vision+overlay"})


class EnumerateJobMessage(ProductEnumerateJob):
    """Decoded SQS body validated by the shared media contract."""

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> "EnumerateJobMessage":
        # Compatibility for messages already queued by the pre-contract
        # publisher. New publishes are contract-exact and omit these.
        normalized = dict(body)
        normalized.pop("version", None)
        normalized.pop("timestamp", None)
        return cls.model_validate(normalized)


def _make_progress_cb(
    *,
    api: ApiClient,
    job_id: UUID,
    claimed_by: str,
    lease_seconds: int,
) -> ProgressCallback:
    """Translate pipeline-emitted ``EnumerationProgressEvent`` rows into
    api heartbeats.

    Each event extends the job lease (so the api stops marking long
    vision+overlay scans as orphaned at the 10-min mark) and advances
    ``product_scan_jobs.progress_pct`` + ``progress_label`` in the UI.

    The pipeline-side ``ProgressThrottler`` already debounces by interval
    + pct delta; here we only need to translate the event shape. We
    swallow any HTTP exception -- a heartbeat 409 (lease lost during the
    pipeline body) or a transient network error MUST NOT abort
    enumeration; the api side handles the orphan via its own janitor and
    the eventual ``/complete`` call returns 409 cleanly.

    Belt + suspenders: the pipeline's throttler ALSO catches callback
    exceptions, so a worker-side raise here would still be swallowed.
    Catching at the boundary keeps the trace local + the log message
    legible.
    """
    def _cb(event: EnumerationProgressEvent) -> None:
        try:
            api.heartbeat(
                job_id=job_id,
                claimed_by=claimed_by,
                stage="enumerating",
                progress_pct=int(event.progress_pct),
                # ``message`` is the human-readable label; falling back to
                # ``phase`` keeps the UI populated even if a future emit
                # point forgets to pass a message string.
                progress_label=event.message or event.phase,
                cost_delta_usd=Decimal("0"),
                lease_seconds=lease_seconds,
            )
        except Exception:
            logger.warning(
                "progress_heartbeat_failed",
                extra={
                    "job_id": str(job_id),
                    "phase": event.phase,
                    "progress_pct": event.progress_pct,
                },
            )
    return _cb


def handle_enumerate_job(
    *,
    message: dict[str, Any],
    settings: WorkerSettings,
    vlm_client: OpenAIVlmClient,
) -> None:
    """Single-message dispatch entrypoint. Raises on any failure; the
    surrounding dispatcher converts exceptions to the matching
    ``error_code`` on the ``/fail`` callback.
    """
    decoded = EnumerateJobMessage.from_dict(message)
    # SECURITY (F3): the API base must come from worker settings only,
    # never from the queue body. ``decoded.callback_base_url`` is held
    # on the dataclass to mirror the contract but is deliberately
    # ignored here.
    api = ApiClient(
        base_url=settings.drive_api_base_url,
        internal_api_key=settings.drive_internal_api_key,
    )
    try:
        # 1. Claim
        # The api returns 409 for "already claimed / completed /
        # cancelled" — duplicate or stale SQS deliveries. Per api
        # contract: ack the message, do not retry. Pre-fix the 409
        # propagated to the dispatcher's generic exception path →
        # /fail attempt (also 409 — we don't own the lease) →
        # re-raise → eventual DLQ for what is a no-op.
        try:
            api.claim(
                job_id=decoded.job_id,
                claimed_by=settings.worker_id,
                next_stage="enumerating",
                lease_seconds=settings.worker_lease_seconds,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                logger.info(
                    "enumerate_claim_conflict_acking_message",
                    extra={
                        "job_id": str(decoded.job_id),
                        "claimed_by": settings.worker_id,
                        "note": (
                            "job already claimed/completed/cancelled — "
                            "ack-delete the SQS message; do not retry"
                        ),
                    },
                )
                return
            raise

        # 2-3. Resolve scenes + download keyframes.
        api.heartbeat(
            job_id=decoded.job_id, claimed_by=settings.worker_id,
            stage="enumerating", progress_pct=10,
            progress_label="Resolving scenes",
            cost_delta_usd=Decimal("0"),
            lease_seconds=settings.worker_lease_seconds,
        )
        keyframes, ocr_by_scene_id, file_name = _fetch_keyframes(
            settings=settings,
            org_id=decoded.org_id,
            video_id=decoded.video_id,
            max_keyframes=decoded.max_keyframes,
        )
        if not keyframes:
            api.fail(
                job_id=decoded.job_id, claimed_by=settings.worker_id,
                cost_delta_usd=Decimal("0"),
                error_code="video_not_found",
                error_message="no scenes / keyframes resolved for video",
            )
            return

        # 4. Run pipeline. SigLIP2 is loaded ONCE and shared by both
        #    passes; the keyframes fetched above are shared too.
        run_vision = decoded.enumeration_mode in _MODES_WITH_VISION
        run_overlay = decoded.enumeration_mode in _MODES_WITH_OVERLAY
        api.heartbeat(
            job_id=decoded.job_id, claimed_by=settings.worker_id,
            stage="enumerating", progress_pct=30,
            progress_label=f"Enumerating ({len(keyframes)} keyframes)",
            cost_delta_usd=Decimal("0"),
            lease_seconds=settings.worker_lease_seconds,
        )
        # Pipeline-emitted progress events become api heartbeats. The
        # pipeline phases populate pct 32..79 between the explicit
        # pct=30 above and the pct=80 "Uploading reference crops" below,
        # so the job lease stays extended through the silent middle of
        # vision+overlay work. See ``_make_progress_cb`` + the
        # ``progress.py`` module in heimdex-media-pipelines.
        progress_cb = _make_progress_cb(
            api=api,
            job_id=decoded.job_id,
            claimed_by=settings.worker_id,
            lease_seconds=settings.worker_lease_seconds,
        )
        siglip = load_siglip(SiglipConfig(model_id=settings.siglip2_model_id))

        # The SAME embedder closure feeds both passes (one loaded model).
        def embedder(imgs):  # noqa: ANN001,ANN202 — local closure
            return embed_pil_image_batch(imgs, loaded=siglip)
        config = EnumerationConfig(
            max_keyframes=decoded.max_keyframes,
            vlm_batch_size=settings.openai_batch_size,
            cluster_cosine_threshold=settings.enum_cluster_cosine_threshold,
            min_supporting_keyframes=settings.enum_min_supporting_keyframes,
            min_prominence_pct=settings.enum_prominence_floor_pct,
            min_enumeration_confidence=settings.enum_min_confidence,
            enumeration_version=decoded.enumeration_version,
        )

        # The vision and overlay passes are SEPARATE functions —
        # orchestration, not coupling. Each produces its own catalog
        # payload (stamped with its source + version); the two lists are
        # concatenated into ONE complete callback.
        vision_products: list[CanonicalProduct] = []
        overlay_products: list[CanonicalProduct] = []
        total_cost = 0.0

        if run_vision:
            try:
                vision_products, vision_cost = _run_vision_pass(
                    keyframes=keyframes,
                    vlm_client=vlm_client,
                    embedder=embedder,
                    config=config,
                    settings=settings,
                    progress_callback=progress_cb,
                )
            except VlmTimeoutError as exc:
                api.fail(
                    job_id=decoded.job_id, claimed_by=settings.worker_id,
                    cost_delta_usd=Decimal("0"),
                    error_code="llm_timeout",
                    error_message=str(exc)[:1900],
                )
                return
            except VlmSchemaError as exc:
                api.fail(
                    job_id=decoded.job_id, claimed_by=settings.worker_id,
                    cost_delta_usd=Decimal("0"),
                    error_code="llm_schema_mismatch",
                    error_message=str(exc)[:1900],
                )
                return
            total_cost += vision_cost

        if run_overlay:
            # Overlay reuses the already-fetched keyframes + the
            # already-loaded OWLv2 (via the vlm_client) + the shared
            # SigLIP2 embedder. In ``vision+overlay`` mode this is an
            # additive best-effort pass — a failure here must NOT discard
            # the vision rows; in ``overlay`` mode it is the only source.
            overlay_products, overlay_cost = _run_overlay_pass(
                keyframes=keyframes,
                ocr_by_scene_id=ocr_by_scene_id,
                file_name=file_name,
                vlm_client=vlm_client,
                embedder=embedder,
                config=config,
                settings=settings,
                progress_callback=progress_cb,
            )
            total_cost += overlay_cost

        # All-rejected != failure — we still post the rejected entries
        # so the API surfaces the empty-state UI honestly. But "0
        # candidate clusters at all" across every requested pass is a
        # legitimate failure.
        all_products = vision_products + overlay_products
        accepted = [p for p in all_products if p.rejected_reason is None]
        if not all_products:
            api.fail(
                job_id=decoded.job_id, claimed_by=settings.worker_id,
                cost_delta_usd=Decimal(str(total_cost)),
                error_code="no_products_detected",
                error_message="enumeration produced 0 candidate clusters",
            )
            return

        # 5. Upload crops + build catalog payload. One helper call per
        #    source so each row carries its own source + version; the
        #    two lists concatenate into a single complete callback.
        api.heartbeat(
            job_id=decoded.job_id, claimed_by=settings.worker_id,
            stage="enumerating", progress_pct=80,
            progress_label="Uploading reference crops",
            cost_delta_usd=Decimal(str(total_cost)),
            lease_seconds=settings.worker_lease_seconds,
        )
        catalog_entries: list[dict[str, Any]] = []
        if vision_products:
            catalog_entries += _upload_crops_and_build_payload(
                settings=settings,
                org_id=decoded.org_id,
                video_id=decoded.video_id,
                products=vision_products,
                enumeration_version=decoded.enumeration_version,
                enumeration_prompt_version=decoded.enumeration_prompt_version,
                enumeration_source=_SOURCE_VISION,
            )
        if overlay_products:
            catalog_entries += _upload_crops_and_build_payload(
                settings=settings,
                org_id=decoded.org_id,
                video_id=decoded.video_id,
                products=overlay_products,
                # Overlay rows carry the pipeline's overlay algo version,
                # NOT the vision enumeration_version from the job message.
                enumeration_version=OVERLAY_ENUMERATION_VERSION,
                enumeration_prompt_version=decoded.enumeration_prompt_version,
                enumeration_source=_SOURCE_OVERLAY,
            )

        # 6. Complete.
        api.complete_enumeration(
            job_id=decoded.job_id, claimed_by=settings.worker_id,
            cost_delta_usd=Decimal("0"),  # already reported in heartbeats
            catalog_entries=catalog_entries,
        )
        logger.info(
            "product_enumerate_completed",
            extra={
                "job_id": str(decoded.job_id),
                "enumeration_mode": decoded.enumeration_mode,
                "candidate_count": len(all_products),
                "accepted_count": len(accepted),
                "vision_count": len(vision_products),
                "overlay_count": len(overlay_products),
                "cost_usd": float(total_cost),
            },
        )
    finally:
        api.close()


# ---------- enumeration passes (vision / overlay) ----------

def _run_vision_pass(
    *,
    keyframes: list[SceneKeyframe],
    vlm_client: OpenAIVlmClient,
    embedder: Any,
    config: EnumerationConfig,
    settings: WorkerSettings,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[CanonicalProduct], float]:
    """The legacy vision pass — byte-identical to the pre-overlay flow.

    Finds products *shown in frame* via OWLv2 → gpt-4o-mini → SigLIP2
    cluster, then applies the rule-based label merge. Raises
    :class:`VlmTimeoutError` / :class:`VlmSchemaError` on model failure
    so the caller maps them to the right ``error_code``.

    ``progress_callback`` (optional) is forwarded to the pipeline so
    api heartbeats can fire at every phase boundary inside the long
    silent stretch between the worker's pct=30 and pct=80 explicit
    pings. Defaults to ``None`` for tests that don't need it.
    """
    # Prompts are ignored by ``OpenAIVlmClient`` in the OWLv2 two-stage
    # refactor — the client owns its own label prompt
    # (``src.owlv2_prompts.LABEL_PROMPT_SYSTEM``) and OWLv2 takes a
    # query list, not a free-form system prompt. We pass empty strings
    # to satisfy the protocol while keeping the pipeline call site
    # unchanged.
    products, total_cost = enumerate_products(
        keyframes=keyframes,
        vlm_client=vlm_client,
        embedder=embedder,
        system_prompt="",
        user_prompt_template="",
        config=config,
        progress_callback=progress_callback,
    )
    products = merge_products_by_label(products, settings=settings)
    return products, total_cost


def _run_overlay_pass(
    *,
    keyframes: list[SceneKeyframe],
    ocr_by_scene_id: dict[str, str],
    file_name: str | None,
    vlm_client: OpenAIVlmClient,
    embedder: Any,
    config: EnumerationConfig,
    settings: WorkerSettings,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[CanonicalProduct], float]:
    """The overlay pass — reads on-screen info-overlay graphics.

    Reuses the SAME keyframes the vision pass got + the SAME loaded
    SigLIP2 embedder + the SAME loaded OWLv2 (via the ``vlm_client``'s
    processor/session/device, wrapped in a thin
    :class:`WorkerOwlV2Detector` adapter). Only the classical cv2
    detector + the gpt-4o-mini overlay reader are overlay-specific.

    ``ocr_by_scene_id`` is the per-scene OCR text from the API's
    ``/internal/videos/{file_id}/scenes-with-keyframes`` response (the
    same call ``_fetch_keyframes`` made for the vision path). Each
    :class:`OverlayKeyframe` MUST carry this string — the Tier 1
    detector reads it for the ``ocr_price`` / ``ocr_text_density`` /
    ``promo_penalty`` signals AND the structural gate. Wiring an empty
    string here (or worse, omitting the argument, which is now a
    ``TypeError`` after the 2026-05-26 fail-loud bump) silently kills
    the OCR half of the gate.
    """
    extractor = OverlayProductExtractor(
        openai_client=vlm_client._client,
        model=settings.overlay_extraction_model,
        daily_cap_usd=settings.overlay_extraction_daily_budget_usd,
        ocr_hint_enabled=settings.overlay_extraction_ocr_hint_enabled,
    )
    owlv2_detector = WorkerOwlV2Detector(
        processor=vlm_client.owlv2_processor,
        session=vlm_client.owlv2_session,
        device=vlm_client.owlv2_device,
        max_image_side=settings.owlv2_max_image_side,
    )

    # Map the shared SceneKeyframe rows to OverlayKeyframe rows. The
    # vision-path keyframe carries ``frame_idx`` (the keyframe ms
    # timestamp); overlay reuses the same value. The already-indexed
    # OCR text for the scene comes through ``ocr_by_scene_id`` — see
    # function docstring + ``_fetch_keyframes``.
    overlay_keyframes = [
        OverlayKeyframe(
            scene_id=kf.scene_id,
            frame_idx=kf.frame_idx,
            image=kf.image,
            ocr_text=ocr_by_scene_id.get(kf.scene_id, ""),
        )
        for kf in keyframes
    ]

    # OCR-blind sub-sample: when the OCR-blind fallback is enabled AND
    # the video's indexed OCR is sparse, the pipelines fallback would
    # send EVERY keyframe to the extractor. Cap that worst-case VLM
    # fan-out by evenly sub-sampling the overlay keyframe list here.
    # Order-preserving; only kicks in when above the cap.
    #
    if (
        should_use_ocr_blind_fallback(
            overlay_keyframes,
            enabled=settings.overlay_ocr_blind_fallback_enabled,
            min_nonempty_ratio=settings.overlay_ocr_blind_fallback_min_nonempty_ratio,
        )
        and len(overlay_keyframes) > settings.overlay_ocr_blind_vlm_cap
    ):
        cap = settings.overlay_ocr_blind_vlm_cap
        step = len(overlay_keyframes) / cap
        sampled = [overlay_keyframes[int(i * step)] for i in range(cap)]
        logger.info(
            "overlay_ocr_blind_sub_sampled in=%d out=%d ratio=%.3f",
            len(overlay_keyframes), cap, ocr_nonempty_ratio(overlay_keyframes),
        )
        overlay_keyframes = sampled

    products, total_cost = enumerate_products_overlay(
        keyframes=overlay_keyframes,
        extractor=extractor,
        owlv2_detector=owlv2_detector,
        embedder=embedder,
        config=config,
        overlay_cosine_threshold=settings.overlay_cluster_cosine_threshold,
        detector_score_threshold=settings.overlay_detector_score_threshold,
        ocr_blind_fallback_enabled=(
            settings.overlay_ocr_blind_fallback_enabled
        ),
        ocr_blind_fallback_min_nonempty_ratio=(
            settings.overlay_ocr_blind_fallback_min_nonempty_ratio
        ),
        ocr_grounding_enabled=settings.overlay_ocr_grounding_enabled,
        ocr_grounding_threshold=settings.overlay_ocr_grounding_threshold,
        ocr_grounding_brand_strip_enabled=(
            settings.overlay_ocr_grounding_brand_strip_enabled
        ),
        ocr_grounding_brand_strategy=(
            settings.overlay_ocr_grounding_brand_strategy
        ),
        ocr_grounding_brand_min_scene_share=(
            settings.overlay_ocr_grounding_brand_min_scene_share
        ),
        ocr_grounding_brand_filename_stopwords_extra=tuple(
            t.strip()
            for t in settings.overlay_ocr_grounding_brand_filename_stopwords_extra.split(",")
            if t.strip()
        ),
        video_file_name=file_name,
        progress_callback=progress_callback,
    )
    return products, total_cost


# ---------- I/O helpers (Phase 2.5b — wired) ----------

def _fetch_keyframes(
    *,
    settings: WorkerSettings,
    org_id: UUID,
    video_id: UUID,
    max_keyframes: int,
    s3_client: S3Client | None = None,
) -> tuple[list[SceneKeyframe], dict[str, str], str | None]:
    """Resolve the scene list via the Phase 2.5a internal endpoint and
    download each scene's keyframe from S3 / MinIO.

    Returns ``(scene_keyframes, ocr_by_scene_id, file_name)``:

    * ``scene_keyframes`` — one :class:`SceneKeyframe` per successfully
      downloaded keyframe. Used by the vision-only enumeration path.
    * ``ocr_by_scene_id`` — ``scene_id -> ocr_text_raw`` for the same
      scenes. Used by the overlay path to populate
      :class:`OverlayKeyframe.ocr_text` (the Tier 1 detector's
      ``ocr_price`` / ``ocr_text_density`` / ``promo_penalty`` signals
      AND structural gate read from this string). The dict carries one
      entry per scene we KEPT — scenes whose keyframe download failed
      drop out of both the list and the map together.
    * ``file_name`` — original Drive upload filename for the video, or
      ``None`` if absent in the API response (older API builds). The
      overlay path uses it as a brand-detection source for OCR
      grounding.

    Returns ``([], {}, None)`` if:
    * the API returns 404 (video not registered) — the caller maps
      this to ``error_code="video_not_found"``;
    * the API returns 0 scenes — same downstream effect;
    * every keyframe download fails — defensive (treats as
      ``video_not_found`` so the worker doesn't burn LLM budget on an
      empty input).

    Per-keyframe download failures (single object missing) are logged
    + skipped; one missing keyframe out of N must not abort the whole
    job. The pipeline tolerates a sparse keyframe set.
    """
    from PIL import Image

    s3 = s3_client if s3_client is not None else S3Client(
        bucket=settings.drive_s3_bucket,
    )

    # SECURITY (F3): URL base must come from worker settings only —
    # never from the queue body. Bearer header travels with this
    # request, so a body-controlled URL would be a credential exfil.
    base = settings.drive_api_base_url.rstrip("/")
    url = f"{base}/internal/videos/{video_id}/scenes-with-keyframes"
    headers = {
        "Authorization": f"Bearer {settings.drive_internal_api_key}",
        "X-Heimdex-Org-Id": str(org_id),
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code == 404:
            logger.info(
                "fetch_keyframes_video_not_found",
                extra={"video_id": str(video_id)},
            )
            return [], {}, None
        resp.raise_for_status()
    except httpx.HTTPError:
        logger.exception(
            "fetch_keyframes_http_error", extra={"video_id": str(video_id)},
        )
        return [], {}, None

    body = resp.json()
    raw_scenes: list[dict[str, Any]] = body.get("scenes", [])
    # API returns ``file_name`` since 2026-05-29 to feed the overlay
    # grounding brand-detection. Older builds omit it — the overlay
    # path tolerates None and falls back to OCR-only auto-detect.
    file_name: str | None = body.get("file_name")
    if not raw_scenes:
        return [], {}, file_name

    # Subsample evenly when the video has more scenes than the cap.
    # Pipeline.enumerate_products also subsamples, but doing it here
    # bounds S3 download cost (we don't fetch keyframes we'll discard).
    if len(raw_scenes) > max_keyframes:
        stride = len(raw_scenes) / max_keyframes
        sampled = [
            raw_scenes[int(i * stride)] for i in range(max_keyframes)
        ]
    else:
        sampled = raw_scenes

    keyframes: list[SceneKeyframe] = []
    ocr_by_scene_id: dict[str, str] = {}
    for scene in sampled:
        s3_key = scene.get("keyframe_s3_key")
        scene_id = scene.get("scene_id")
        if not s3_key or not scene_id:
            continue
        raw = s3.get_object_bytes(s3_key)
        if raw is None:
            # ``get_object_bytes`` returns None on NoSuchKey or
            # transient errors (sdk-level retry already exhausted).
            # Skip and let the rest of the keyframes carry the job.
            logger.warning(
                "fetch_keyframes_missing_s3_object",
                extra={"video_id": str(video_id), "s3_key": s3_key},
            )
            continue
        try:
            image = Image.open(io.BytesIO(raw))
            image.load()  # force decode now so we surface PIL errors here
        except Exception:
            logger.warning(
                "fetch_keyframes_decode_failed",
                extra={"video_id": str(video_id), "s3_key": s3_key},
                exc_info=True,
            )
            continue
        # ``frame_idx`` semantically carries the keyframe's millisecond
        # timestamp. The contracts schema names it ``keyframe_frame_idx``
        # which is mildly misleading — see the schemas comment. Using
        # ms is acceptable because nothing downstream decodes by
        # absolute frame number.
        kf_ts = scene.get("keyframe_timestamp_ms") or 0
        keyframes.append(
            SceneKeyframe(
                scene_id=str(scene_id),
                frame_idx=int(kf_ts),
                image=image,
            )
        )
        # Capture the already-indexed OCR text from the API response.
        # The overlay path's Tier 1 detector reads this for the
        # ``ocr_price`` / ``ocr_text_density`` / ``promo_penalty``
        # signals AND the structural gate. Empty string is a legitimate
        # value when the OCR enrichment hasn't completed for this scene
        # yet — the detector then falls back to the ``rect >= 0.5`` arm
        # of the gate.
        ocr_by_scene_id[str(scene_id)] = scene.get("ocr_text_raw") or ""

    return keyframes, ocr_by_scene_id, file_name


def _upload_crops_and_build_payload(
    *,
    settings: WorkerSettings,
    org_id: UUID,
    video_id: UUID,
    products: list[CanonicalProduct],
    enumeration_version: str,
    enumeration_prompt_version: str,
    enumeration_source: str = "vision",
    s3_client: S3Client | None = None,
) -> list[dict[str, Any]]:
    """Upload each product's canonical crop to S3 and build the
    catalog-entry payload for the API ``complete`` callback.

    The S3 key uses a worker-generated UUID (NOT the future API row
    id — the worker doesn't know that yet, and content-addressable
    schemes would entangle the storage path with detection drift).
    The catalog row's id is generated by Postgres on insert; the link
    between row and crop is via the persisted ``canonical_crop_s3_key``
    field.

    ``enumeration_source`` ("vision" / "overlay") stamps every row from
    this call. The vision and overlay passes call this helper once each
    with their own source + version; the caller concatenates the two
    payload lists into a single ``complete`` callback.

    Payload shape MUST match
    ``app.modules.shorts_auto_product.internal_router._CatalogEntryPayload``
    exactly. Drift here = 400 on the complete callback.
    """
    s3 = s3_client if s3_client is not None else S3Client(
        bucket=settings.drive_s3_bucket,
    )

    payloads: list[dict[str, Any]] = []
    for product in products:
        crop_uuid = _uuid.uuid4()
        s3_key = f"products/{org_id}/{video_id}/{crop_uuid}.jpg"
        try:
            buf = io.BytesIO()
            product.canonical_crop.convert("RGB").save(
                buf, format="JPEG", quality=90, optimize=True,
            )
            buf.seek(0)
            s3._client.put_object(  # type: ignore[attr-defined]
                Bucket=s3.bucket,
                Key=s3_key,
                Body=buf.getvalue(),
                ContentType="image/jpeg",
            )
        except Exception:
            # Don't fail the entire job on a single upload — but we
            # MUST not include this entry in the payload (the API
            # would persist a row pointing at a missing object, which
            # is worse than dropping the product silently).
            logger.exception(
                "upload_canonical_crop_failed",
                extra={"video_id": str(video_id), "crop_uuid": str(crop_uuid)},
            )
            continue

        payloads.append({
            "canonical_crop_s3_key": s3_key,
            "canonical_video_id": str(video_id),
            "canonical_frame_idx": product.canonical_frame_idx,
            "canonical_bbox": {
                "x": int(product.canonical_bbox_xywh[0]),
                "y": int(product.canonical_bbox_xywh[1]),
                "w": int(product.canonical_bbox_xywh[2]),
                "h": int(product.canonical_bbox_xywh[3]),
            },
            "llm_label": product.llm_label,
            "siglip2_embedding": list(product.siglip2_embedding),
            "enumeration_confidence": float(product.enumeration_confidence),
            "prominence_score": float(product.prominence_score),
            "enumeration_version": enumeration_version,
            "enumeration_prompt_version": enumeration_prompt_version,
            # Per-row provenance — the API stops hardcoding "vision" and
            # persists this verbatim (CHECK constraint allows it).
            "enumeration_source": enumeration_source,
        })
    return payloads
