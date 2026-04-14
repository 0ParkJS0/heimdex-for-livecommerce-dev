"""Internal blur callbacks for ``drive-blur-worker``.

Auth is the shared ``DRIVE_INTERNAL_API_KEY`` (``verify_internal_token``),
not user auth — this router is only reachable from inside the VPC over
the internal service network.

Three endpoints:

* ``POST /internal/blur/{job_id}/claim`` — worker asks the API to
  atomically transition ``queued → running`` and receives a lease token.
* ``POST /internal/blur/{job_id}/heartbeat`` — worker extends its lease
  during long OWLv2 runs.
* ``POST /internal/blur/{job_id}/complete`` — terminal result callback.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.dependencies import verify_internal_token
from app.modules.blur.models import (
    BLUR_STATUS_CANCELLED,
    BLUR_STATUS_QUEUED,
    BLUR_STATUS_RUNNING,
)
from app.modules.blur.repository import BlurJobRepository
from app.modules.blur.schemas import (
    BlurJobClaim,
    BlurJobCompletePayload,
    BlurJobHeartbeatPayload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/blur", tags=["internal-blur"])


@router.post("/{job_id}/claim", response_model=BlurJobClaim)
async def claim_blur_job(
    job_id: UUID,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> BlurJobClaim:
    """Atomic ``queued → running`` with a fresh lease token."""
    settings = get_settings()
    repo = BlurJobRepository(db)

    # Inspect current state first so we can return the right error.
    existing = await repo.get_by_id_internal(job_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blur job not found",
        )
    if existing.status == BLUR_STATUS_CANCELLED:
        # User cancelled after enqueue, before claim. Worker should
        # treat this as a normal drop — the SQS message gets deleted
        # and no work happens.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Blur job was cancelled",
        )
    if existing.status != BLUR_STATUS_QUEUED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Blur job is in status={existing.status!r}, expected queued",
        )

    claimed = await repo.claim(
        job_id=job_id,
        lease_seconds=settings.blur_lease_seconds,
    )
    if claimed is None:
        # Race: another worker just claimed it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Blur job was claimed by another worker",
        )
    job, lease_token = claimed
    logger.info("blur_job_claimed", job_id=str(job_id), lease_token=str(lease_token))
    assert job.lease_expires_at is not None
    return BlurJobClaim(
        id=job.id,
        org_id=job.org_id,
        file_id=job.file_id,
        video_id=job.video_id,
        source_s3_key=job.source_s3_key,
        source_kind=job.source_kind,
        options=job.options,
        lease_token=lease_token,
        lease_expires_at=job.lease_expires_at,
    )


@router.post("/{job_id}/heartbeat")
async def heartbeat_blur_job(
    job_id: UUID,
    payload: BlurJobHeartbeatPayload,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    settings = get_settings()
    repo = BlurJobRepository(db)
    ok = await repo.heartbeat(
        job_id=job_id,
        lease_token=payload.lease_token,
        lease_seconds=settings.blur_lease_seconds,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lease lost — job no longer in running state or lease token mismatched",
        )
    return {"ok": True, "job_id": str(job_id)}


@router.post("/{job_id}/complete")
async def complete_blur_job(
    job_id: UUID,
    payload: BlurJobCompletePayload,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    """Terminal transition from the worker.

    Enforces lease-token match: a watchdog-replaced worker cannot stomp
    on a fresh worker's result. If the row was cancelled mid-run, the
    worker still calls complete() — but the status update will no-op
    because the status is no longer ``running``. In that case the
    worker is responsible for deleting any partial S3 output it
    uploaded.
    """
    repo = BlurJobRepository(db)

    existing = await repo.get_by_id_internal(job_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blur job not found",
        )

    # If the job was cancelled mid-run, tell the worker explicitly so
    # it can clean up the partial S3 upload. This is a soft error —
    # the worker treats it as "finish the SQS message, delete the
    # blurred file you wrote, don't retry".
    if existing.status == BLUR_STATUS_CANCELLED:
        logger.info(
            "blur_job_complete_after_cancel",
            job_id=str(job_id),
        )
        return {
            "ok": False,
            "job_id": str(job_id),
            "reason": "cancelled",
            "cleanup_required": True,
        }

    if existing.status != BLUR_STATUS_RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Blur job is in status={existing.status!r}, expected running",
        )

    summary = (
        payload.detections_summary.model_dump()
        if payload.detections_summary is not None
        else None
    )
    refreshed = await repo.complete(
        job_id=job_id,
        lease_token=payload.lease_token,
        status=payload.status,
        blurred_s3_key=payload.blurred_s3_key,
        manifest_s3_key=payload.manifest_s3_key,
        detections_summary=summary,
        error=payload.error,
    )
    if refreshed is None:
        # Lease mismatch — likely a stale worker.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lease token mismatch or job no longer running",
        )
    logger.info(
        "blur_job_completed",
        job_id=str(job_id),
        status=payload.status,
    )
    return {"ok": True, "job_id": str(job_id), "status": payload.status}
