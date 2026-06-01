import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session, get_reprocess_repository, get_scene_opensearch_client
from app.modules.search.scene_client import SceneSearchClient
from app.modules.videos.reprocess_repository import ReprocessRepository
from app.sqs_producer import (
    publish_enrichment_jobs,
    publish_scene_enrichment_jobs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["videos-internal"])

from app.dependencies import verify_internal_token as _verify_internal_token


async def _publish_scene_jobs_in_background(
    *,
    file_id: UUID,
    org_id: UUID,
    video_id: str,
    scenes: list[dict[str, Any]],
) -> None:
    """Publish per-scene SQS messages in a background thread.

    Runs ``publish_scene_enrichment_jobs`` via ``run_in_executor`` so the
    synchronous boto3 ``send_message_batch`` calls don't block the event loop.
    Called from ``asyncio.create_task()`` after the PATCH response is sent.
    """
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: publish_scene_enrichment_jobs(
                file_id=file_id,
                org_id=org_id,
                video_id=video_id,
                scenes=scenes,
            ),
        )
        logger.info(
            "reprocess_scene_enrichment_jobs_published",
            extra={"video_id": video_id, "scene_count": len(scenes)},
        )
    except Exception:
        logger.warning(
            "reprocess_scene_enrichment_jobs_failed",
            extra={"video_id": video_id, "scene_count": len(scenes)},
            exc_info=True,
        )


@router.delete("/{video_id}/scenes")
async def delete_video_scenes(
    video_id: str,
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    scene_client: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    deleted = await scene_client.delete_scenes_by_video_id(str(org_id), video_id)
    return {"deleted": deleted}


@router.patch("/{video_id}/reprocess/{job_id}/status")
async def update_reprocess_status(
    video_id: str,
    job_id: str,
    status_value: str = Body(..., alias="status"),
    scene_count: int | None = Body(None),
    error: str | None = Body(None),
    org_id: str | None = Body(None),
    keyframe_s3_prefix: str | None = Body(None),
    audio_s3_key: str | None = Body(None),
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
    repo: ReprocessRepository = Depends(get_reprocess_repository),
):
    try:
        parsed_job_id = UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid job_id format",
        )

    await repo.update_status(
        parsed_job_id,
        status_value,
        scene_count=scene_count,
        error=error,
    )

    # Publish enrichment SQS jobs when resplit completes successfully.
    # Mirrors the pattern in internal_processing_router.py and
    # youtube/internal_router.py — enrichment fires as a side effect
    # of status transitioning to 'completed'.
    if (
        status_value == "completed"
        and scene_count
        and scene_count > 0
        and org_id
        and keyframe_s3_prefix
    ):
        file_uuid = await _resolve_file_id(db, video_id, UUID(org_id))
        if file_uuid is not None:
            parsed_org_id = UUID(org_id)
            if video_id.startswith("gd_"):
                await _update_drive_file_after_reprocess(
                    db=db,
                    file_id=file_uuid,
                    scene_count=scene_count,
                    keyframe_s3_prefix=keyframe_s3_prefix,
                    audio_s3_key=audio_s3_key,
                )

            # v1: per-video enrichment for STT, OCR, face
            publish_enrichment_jobs(
                file_id=file_uuid,
                org_id=parsed_org_id,
                video_id=video_id,
                keyframe_s3_prefix=keyframe_s3_prefix,
                audio_s3_key=audio_s3_key,
            )

            # v2: per-scene enrichment for caption + visual-embed
            scenes_for_publish = [
                {
                    "scene_id": f"{video_id}_scene_{i:03d}",
                    "scene_index": i,
                    "keyframe_s3_key": f"{keyframe_s3_prefix}{video_id}_scene_{i:03d}.jpg",
                }
                for i in range(scene_count)
            ]
            asyncio.create_task(
                _publish_scene_jobs_in_background(
                    file_id=file_uuid,
                    org_id=parsed_org_id,
                    video_id=video_id,
                    scenes=scenes_for_publish,
                )
            )

            logger.info(
                "reprocess_enrichment_published",
                extra={
                    "video_id": video_id,
                    "job_id": job_id,
                    "scene_count": scene_count,
                    "file_id": str(file_uuid),
                },
            )

    return {"status": "ok"}


async def _update_drive_file_after_reprocess(
    *,
    db: AsyncSession,
    file_id: UUID,
    scene_count: int,
    keyframe_s3_prefix: str,
    audio_s3_key: str | None,
) -> None:
    """Keep DriveFile metadata aligned with the scene docs just re-ingested."""
    from sqlalchemy import update

    from app.modules.drive.models import DriveFile

    values: dict[str, Any] = {
        "scene_count": scene_count,
        "keyframe_s3_prefix": keyframe_s3_prefix,
    }
    if audio_s3_key is not None:
        values["audio_s3_key"] = audio_s3_key or None

    await db.execute(
        update(DriveFile)
        .where(DriveFile.id == file_id)
        .values(**values)
    )
    await db.flush()


# ---------------------------------------------------------------------------
# Pattern B internal-auth helper
# ---------------------------------------------------------------------------
#
# The scenes-with-keyframes endpoint authenticates workers via the shared
# internal bearer and then needs to scope its work to a specific tenant. Until
# 2026-05-01 it did this with **Pattern A**: caller asserts the tenant via the
# ``X-Heimdex-Org-Id`` header, and the repo lookup filters by both ``file_id``
# AND the asserted ``org_id`` so an attacker faking the header gets a 404. That
# works as long as the (file_id, org_id) pair can't leak together — fragile,
# easy to regress, and inconsistent with how the blur / shorts_auto_product
# internal endpoints already operate.
#
# Codex adversarial review F1 (2026-05-01) flagged this as a multi-tenant
# isolation gap. Fix: migrate to **Pattern B** — bearer authenticates the
# call; the resource's own ``org_id`` is the canonical tenant context;
# the asserted header becomes an OPTIONAL cross-validation that returns
# 404 (not 400) on mismatch so timing doesn't leak the correct org.
#
# Workers continue to send the header (no worker code changes), so this
# is fully backward-compatible. Future endpoints in this file should use
# the helper; future endpoints elsewhere should look at this as the
# template for the platform sweep tracked separately.
#
# Specifically NOT applied to YouTube paths in this file (``_resolve_file_id``,
# delete/reprocess endpoints) — those have separate threat models /
# behavioral contracts and migrate in their own PR.

async def _resolve_drive_file_with_org(
    *,
    file_id: UUID,
    x_heimdex_org_id: str | None,
    db: AsyncSession,
) -> tuple[Any, UUID]:
    """Pattern B resolver for DriveFiles. Thin wrapper over the
    shared ``app.lib.internal_auth.resolve_resource_with_org`` helper
    so this file's three endpoints (and any new ones) get identical
    semantics with the rest of the platform sweep.

    Look up by id alone (no org filter) — the resource's ``org_id``
    is the canonical tenant context. ``x_heimdex_org_id`` (when sent)
    is a soft cross-validation that 404s on mismatch. See the helper's
    docstring for the full design rationale + non-negotiables.
    """
    from app.lib.internal_auth import resolve_resource_with_org
    from app.modules.drive.repository import DriveFileRepository

    repo = DriveFileRepository(db)

    async def _lookup(rid: UUID):
        return await repo.get_by_id_resource_scoped(file_id=rid)

    return await resolve_resource_with_org(
        resource_id=file_id,
        x_heimdex_org_id=x_heimdex_org_id,
        lookup_fn=_lookup,
        not_found_detail="video not found",
    )


@router.get("/{file_id}/scenes-with-keyframes")
async def get_scenes_with_keyframes(
    file_id: UUID,
    x_heimdex_org_id: str | None = Header(default=None, alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
    scene_client: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    """Phase 2.5a — internal lookup for the shorts-auto product mode v2
    workers (enumerate + track).

    Resolves a ``DriveFile`` UUID into the chronologically-ordered list
    of scenes for that video, augmented with the keyframe S3 key
    (constructed via the canonical ``enrichment_keyframe_s3_key``
    helper). Both new product workers consume this; keeping the join
    server-side avoids each worker re-implementing the
    ``DriveFile`` → string ``video_id`` translation + key construction
    independently (drift between them would silently produce 404s on
    the worker side).

    Auth (Pattern B, post-2026-05-01): bearer authenticates the call;
    the resource's ``org_id`` is the canonical tenant context.
    ``X-Heimdex-Org-Id`` is OPTIONAL and treated as a cross-validation
    only — a mismatch returns 404 (not 403) so timing doesn't leak the
    correct tenant. See module-level helper docstring for rationale.

    Response shape (stable; both workers depend on it)::

        {
          "video_id": "gd_<...>",        # string id used by OS
          "drive_file_id": "<uuid>",
          "file_name": "<original drive upload filename>",
          "total_duration_ms": <int>,    # max(end_ms) across scenes
          "proxy_s3_key": "<org>/drive/<drive>/<gfid>/proxy.mp4" | null,
          "scenes": [
            {
              "scene_id": "gd_<...>_scene_007",
              "start_ms": <int>,
              "end_ms": <int>,
              "keyframe_timestamp_ms": <int|null>,
              "keyframe_s3_key": "<org>/drive/keyframes/<video>/<scene>.jpg",
              "ocr_text_raw": "<concatenated OCR text or ''>"
            },
            ...
          ]
        }

    ``ocr_text_raw`` mirrors the OpenSearch scene's already-indexed OCR
    field. The product-enumerate-worker's overlay Tier 1 detector reads
    this for the ``ocr_price`` / ``ocr_text_density`` / ``promo_penalty``
    signals AND for the structural gate. Empty string is a legitimate
    value (scene has no OCR — usually because the OCR enrichment hasn't
    completed yet); the worker forwards it verbatim and the detector's
    gate then falls back to the ``rect >= 0.5`` arm.

    ``proxy_s3_key`` mirrors ``DriveFile.proxy_s3_key`` verbatim
    (canonical path written by drive-transcode-worker via
    ``heimdex_worker_sdk.drive_keys.proxy_s3_key``). It is ``None``
    when transcode hasn't completed for this video; callers should
    treat that as a terminal "not ready" state rather than retry —
    the field only flips populated after a successful transcode.
    Internal media consumers use this field to download the full proxy
    once and slice scene windows in-memory, instead of reaching for a
    per-scene mp4 (which doesn't exist).
    """
    from app.modules.drive.keys import enrichment_keyframe_s3_key

    drive_file, org_id = await _resolve_drive_file_with_org(
        file_id=file_id,
        x_heimdex_org_id=x_heimdex_org_id,
        db=db,
    )
    video_id_str: str = drive_file.video_id

    # Pull all scenes for this video. ``page_size`` is generous —
    # 500 covers > 99% of livecommerce videos (45s default split,
    # ~4hr cap → ~320 scenes). Bumping to 5000 if a longer video
    # surfaces.
    response = await scene_client.get_video_scenes(
        org_id=str(org_id),
        video_id=video_id_str,
        page_size=500,
        offset=0,
    )
    raw_scenes = response.get("scenes", [])

    enriched: list[dict[str, Any]] = []
    total_duration_ms = 0
    for scene in raw_scenes:
        scene_id = scene.get("scene_id")
        if not scene_id:
            # Defensive: drop malformed rows rather than 500 the worker.
            continue
        start_ms = int(scene.get("start_ms", 0))
        end_ms = int(scene.get("end_ms", 0))
        total_duration_ms = max(total_duration_ms, end_ms)
        kf_ts = scene.get("keyframe_timestamp_ms")
        enriched.append({
            "scene_id": scene_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "keyframe_timestamp_ms": (
                int(kf_ts) if kf_ts is not None else None
            ),
            # Canonical key — same helper drive-worker uses when it
            # wrote the keyframe. Drift-proof by construction.
            "keyframe_s3_key": enrichment_keyframe_s3_key(
                str(org_id), video_id_str, scene_id,
            ),
            # Already-indexed OCR text on the OS scene doc — the
            # product-enumerate-worker overlay path reads this for the
            # Tier 1 detector's OCR-side signals + structural gate.
            # ``None``/missing maps to ``""`` so the worker contract
            # stays a plain string. Same pattern as the
            # internal media consumers.
            "ocr_text_raw": scene.get("ocr_text_raw") or "",
        })

    # Defensive ordering — ``get_video_scenes`` already sorts by
    # start_ms ascending when no query is supplied, but a downstream
    # change there shouldn't silently break the worker's chronological
    # iteration assumption.
    enriched.sort(key=lambda s: s["start_ms"])

    return {
        "video_id": video_id_str,
        "drive_file_id": str(file_id),
        # Original Drive upload filename. Worker uses this as one of two
        # brand-detection sources for overlay OCR grounding (the other is
        # OCR-frequency auto-detect). Korean livecommerce filenames
        # follow ``YYMMDD_<brand>[ ...]`` convention so the brand prefix
        # is reliable. Backwards-compat: older worker builds that don't
        # consume this key simply ignore it.
        "file_name": drive_file.file_name,
        "total_duration_ms": total_duration_ms,
        # ``DriveFile.proxy_s3_key`` is nullable — None means transcode
        # hasn't completed. Pass through verbatim; callers decide how
        # to surface that to the user.
        "proxy_s3_key": drive_file.proxy_s3_key,
        "scenes": enriched,
    }


async def _resolve_file_id(
    db: AsyncSession, video_id: str, org_id: UUID,
) -> UUID | None:
    """Look up the real DriveFile or YouTubeVideo UUID for enrichment tracking.

    Enrichment workers use this UUID to report per-file enrichment status.
    Kept as a separate function to avoid coupling the status handler to
    repository internals.
    """
    if video_id.startswith("gd_"):
        from app.modules.drive.repository import DriveFileRepository
        repo = DriveFileRepository(db)
        drive_file = await repo.get_by_video_id(org_id, video_id)
        return drive_file.id if drive_file else None
    elif video_id.startswith("yt_"):
        from app.modules.youtube.repository import YouTubeVideoRepository
        repo = YouTubeVideoRepository(db)
        yt_video = await repo.get_by_video_id(org_id, video_id)
        return yt_video.id if yt_video else None
    return None
