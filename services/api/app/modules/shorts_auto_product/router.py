"""Public routes for shorts-auto product mode v2.

Mounted under ``/api/shorts/auto/products`` (catalog + scan + clip)
and ``/api/shorts/auto/jobs`` (job lifecycle). All routes require an
authenticated user and a resolved org context.

Tenant isolation: every public method on
:class:`ProductScanService` already filters on ``org_id`` from the
:class:`OrgContext` dependency; this router only forwards the
context, never trusting path-supplied org / user ids.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.base import get_db_session
from app.modules.auth.service import get_current_user
from app.modules.shorts_auto_product.schemas import (
    ClipRequest,
    ClipResponse,
    JobStatusResponse,
    ProductCatalogResponse,
    ProductV2AvailabilityFragment,
    RescanResponse,
    ScanRequest,
    ScanResponse,
)
from app.modules.shorts_auto_product.service import ProductScanService
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

logger = logging.getLogger(__name__)

# Mount under /api/shorts/auto so the existing v1 endpoints
# (/api/shorts/auto-select, /auto-render, /auto-availability) keep
# working unchanged. The /products/* and /jobs/* sub-trees are
# v2-only.
#
# main.py adds the ``/api`` prefix on include_router; this router
# only carries the in-module prefix, mirroring shorts_auto/router.py.
router = APIRouter(prefix="/shorts/auto", tags=["shorts-auto-product-v2"])


def _build_service(
    db: AsyncSession,
    settings: Settings,
) -> ProductScanService:
    return ProductScanService(session=db, settings=settings)


# ----------------------------------------------------------------------
# GET /api/shorts/auto/products/{video_id}
# ----------------------------------------------------------------------

@router.get(
    "/products/{video_id}",
    response_model=ProductCatalogResponse,
)
async def get_product_catalog(
    video_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProductCatalogResponse:
    """List enumerated products for a video.

    Empty ``products`` array + ``scan_status="never"`` means the user
    should see the "Scan for products" CTA. ``scan_status="in_progress"``
    means the toast subscription should be reattached to ``scan_job_id``.
    """
    service = _build_service(db, settings)
    return await service.list_products(
        org_id=org_ctx.org_id, video_id=video_id,
    )


# ----------------------------------------------------------------------
# POST /api/shorts/auto/products/{video_id}/scan
# ----------------------------------------------------------------------

@router.post(
    "/products/{video_id}/scan",
    response_model=ScanResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_scan(
    video_id: UUID,
    body: ScanRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ScanResponse:
    """Enqueue an enumeration scan.

    Idempotent within ``auto_shorts_product_v2_scan_idempotency_seconds``
    (default 60s) per ``(video_id, user_id)``: re-clicking returns the
    existing job. 402 on cost cap. 429 on per-org concurrency cap.
    """
    service = _build_service(db, settings)
    return await service.enqueue_scan(
        org_id=org_ctx.org_id,
        video_id=video_id,
        user_id=user.id,
        duration_preset_sec=body.duration_preset_sec,
    )


# ----------------------------------------------------------------------
# POST /api/shorts/auto/products/{video_id}/{catalog_entry_id}/clip
# ----------------------------------------------------------------------

@router.post(
    "/products/{video_id}/{catalog_entry_id}/clip",
    response_model=ClipResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_clip(
    video_id: UUID,
    catalog_entry_id: UUID,
    body: ClipRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ClipResponse:
    """Enqueue tracking + assembly + render for a chosen catalog entry.

    Same idempotency / cap semantics as ``/scan`` but keyed on
    ``(video_id, user_id, catalog_entry_id)``.
    """
    service = _build_service(db, settings)
    return await service.enqueue_clip(
        org_id=org_ctx.org_id,
        video_id=video_id,
        catalog_entry_id=catalog_entry_id,
        user_id=user.id,
        duration_preset_sec=body.duration_preset_sec,
    )


# ----------------------------------------------------------------------
# POST /api/shorts/auto/products/{video_id}/rescan
# ----------------------------------------------------------------------

@router.post(
    "/products/{video_id}/rescan",
    response_model=RescanResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def force_rescan(
    video_id: UUID,
    body: ScanRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RescanResponse:
    """Soft-reject the existing catalog and enqueue a fresh enumeration.

    Bypasses the 60s idempotency window — rescan is always intentional.
    Existing appearances cascade naturally (rejected catalog rows hide
    from the gallery; their appearances stay readable for forensics).
    """
    service = _build_service(db, settings)
    return await service.rescan(
        org_id=org_ctx.org_id,
        video_id=video_id,
        user_id=user.id,
        duration_preset_sec=body.duration_preset_sec,
    )


# ----------------------------------------------------------------------
# DELETE /api/shorts/auto/products/{video_id}/{catalog_entry_id}
# ----------------------------------------------------------------------

@router.delete(
    "/products/{video_id}/{catalog_entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reject_catalog_entry(
    video_id: UUID,
    catalog_entry_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Soft-reject a catalog entry ("this isn't a product").

    v1: internal admin use. v2 will surface this in the picker UI for
    user-driven curation. Idempotent — already-rejected entries return
    204 silently.
    """
    service = _build_service(db, settings)
    await service.reject_catalog_entry(
        org_id=org_ctx.org_id,
        video_id=video_id,
        catalog_entry_id=catalog_entry_id,
    )


# ----------------------------------------------------------------------
# GET /api/shorts/auto/jobs/{job_id}
# ----------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
)
async def get_job_status(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JobStatusResponse:
    """Poll job status. Drives the in-app toast subscription."""
    service = _build_service(db, settings)
    return await service.get_job_status(
        org_id=org_ctx.org_id, job_id=job_id,
    )


# ----------------------------------------------------------------------
# POST /api/shorts/auto/jobs/{job_id}/cancel
# ----------------------------------------------------------------------

@router.post(
    "/jobs/{job_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_job(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Cancel an in-flight scan or clip job.

    Best-effort: marks the job ``cancelled``. The worker bails out at
    its next heartbeat. Already-terminal jobs return 404 (no info leak
    between not-found and already-done).
    """
    service = _build_service(db, settings)
    await service.cancel_job(org_id=org_ctx.org_id, job_id=job_id)


# ----------------------------------------------------------------------
# GET /api/shorts/auto/products-v2-availability
# ----------------------------------------------------------------------

@router.get(
    "/products-v2-availability",
    response_model=ProductV2AvailabilityFragment,
)
async def get_product_v2_availability(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProductV2AvailabilityFragment:
    """Frontend reads this to decide whether to render the v2 UI.

    Plan §5 originally proposed merging this fragment into the
    existing ``/auto-availability`` payload. Phase 1 keeps it as a
    separate endpoint to avoid touching the v1 shorts-auto module —
    we can fold them together in a later phase if desired.
    """
    service = _build_service(db, settings)
    return await service.availability_fragment(org_id=org_ctx.org_id)
