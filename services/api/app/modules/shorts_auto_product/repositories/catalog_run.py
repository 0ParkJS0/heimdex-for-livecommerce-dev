"""ProductCatalogRunRepository — readiness state for product catalogs."""

from __future__ import annotations

from datetime import datetime, timezone
import inspect
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.shorts_auto_product.models import (
    CATALOG_STATUS_AUGMENTING_STT,
    CATALOG_STATUS_CONSOLIDATING,
    CATALOG_STATUS_ENUMERATING,
    CATALOG_STATUS_FAILED,
    CATALOG_STATUS_QUEUED,
    CATALOG_STATUS_READY,
    ProductCatalogRun,
)


class ProductCatalogRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_for_scan(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        scan_job_id: UUID,
        source_mode: str,
        overlay_policy: str,
    ) -> ProductCatalogRun:
        run = ProductCatalogRun(
            org_id=org_id,
            video_id=video_id,
            scan_job_id=scan_job_id,
            status=CATALOG_STATUS_QUEUED,
            source_mode=source_mode,
            overlay_policy=overlay_policy,
        )
        self.session.add(run)
        await _maybe_await(self.session.flush())
        return run

    async def latest_for_video(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
    ) -> ProductCatalogRun | None:
        stmt = (
            select(ProductCatalogRun)
            .where(
                ProductCatalogRun.org_id == org_id,
                ProductCatalogRun.video_id == video_id,
            )
            .order_by(ProductCatalogRun.created_at.desc(), ProductCatalogRun.id.desc())
            .limit(1)
        )
        result = await _maybe_await(self.session.execute(stmt))
        return result.scalar_one_or_none()

    async def mark_enumerating(self, *, scan_job_id: UUID) -> None:
        await self._update_by_scan_job(
            scan_job_id=scan_job_id,
            values={"status": CATALOG_STATUS_ENUMERATING},
        )

    async def mark_after_worker_complete(
        self,
        *,
        scan_job_id: UUID,
        source_mode: str,
        next_status: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        values: dict[str, object] = {"status": next_status}
        if "vision" in source_mode:
            values["vision_completed_at"] = now
        if "overlay" in source_mode:
            values["overlay_completed_at"] = now
        if next_status == CATALOG_STATUS_READY:
            values["finalized_at"] = now
        await self._update_by_scan_job(scan_job_id=scan_job_id, values=values)

    async def mark_augmenting_stt(self, *, org_id: UUID, video_id: UUID) -> None:
        await self._update_latest_by_video(
            org_id=org_id,
            video_id=video_id,
            values={"status": CATALOG_STATUS_AUGMENTING_STT},
        )

    async def mark_stt_complete(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        next_status: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        values: dict[str, object] = {
            "status": next_status,
            "stt_completed_at": now,
        }
        if next_status == CATALOG_STATUS_READY:
            values["finalized_at"] = now
        await self._update_latest_by_video(
            org_id=org_id, video_id=video_id, values=values,
        )

    async def mark_consolidating(self, *, org_id: UUID, video_id: UUID) -> None:
        await self._update_latest_by_video(
            org_id=org_id,
            video_id=video_id,
            values={"status": CATALOG_STATUS_CONSOLIDATING},
        )

    async def mark_consolidation_complete(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
    ) -> None:
        now = datetime.now(timezone.utc)
        await self._update_latest_by_video(
            org_id=org_id,
            video_id=video_id,
            values={
                "status": CATALOG_STATUS_READY,
                "consolidation_completed_at": now,
                "finalized_at": now,
            },
        )

    async def mark_failed(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        error_code: str,
        error_message: str,
    ) -> None:
        await self._update_latest_by_video(
            org_id=org_id,
            video_id=video_id,
            values={
                "status": CATALOG_STATUS_FAILED,
                "error_code": error_code,
                "error_message": error_message[:2000],
            },
        )

    async def _update_by_scan_job(
        self,
        *,
        scan_job_id: UUID,
        values: dict[str, object],
    ) -> None:
        stmt = (
            update(ProductCatalogRun)
            .where(ProductCatalogRun.scan_job_id == scan_job_id)
            .values(**values)
        )
        await _maybe_await(self.session.execute(stmt))
        await _maybe_await(self.session.flush())

    async def _update_latest_by_video(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        values: dict[str, object],
    ) -> None:
        latest = await self.latest_for_video(org_id=org_id, video_id=video_id)
        if latest is None:
            return
        stmt = (
            update(ProductCatalogRun)
            .where(ProductCatalogRun.id == latest.id)
            .values(**values)
        )
        await _maybe_await(self.session.execute(stmt))
        await _maybe_await(self.session.flush())


__all__ = ["ProductCatalogRunRepository"]


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value
