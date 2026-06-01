"""Product v2 state-machine regression tests.

The SAM2 product-track worker is retired. These tests keep the useful
state-response and enumeration-callback coverage while asserting that
legacy tracker callbacks are no longer accepted.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.shorts_auto_product.models import (
    SCAN_MODE_ENUMERATE,
    SCAN_MODE_RENDER_CHILD,
    SCAN_MODE_SCAN_ORDER,
    SCAN_STAGE_QUEUED,
)
from app.modules.shorts_auto_product.service import _job_to_status_response


def _job_row(
    *,
    job_id: UUID | None = None,
    mode: str = SCAN_MODE_ENUMERATE,
    catalog_entry_id: UUID | None = None,
    parent_job_id: UUID | None = None,
    shorts_index: int | None = None,
    render_job_id: UUID | None = None,
    stage: str = SCAN_STAGE_QUEUED,
):
    job = MagicMock()
    job.id = job_id if job_id is not None else uuid4()
    job.mode = mode
    job.catalog_entry_id = catalog_entry_id
    job.parent_job_id = parent_job_id
    job.shorts_index = shorts_index
    job.render_job_id = render_job_id
    job.stage = stage
    job.progress_pct = 0
    job.progress_label = None
    job.completed_at = None
    job.failed_at = None
    job.cancelled_at = None
    job.error_code = None
    job.error_message = None
    job.cost_usd_estimate = Decimal("0")
    return job


def test_status_response_enumerate_mode_no_catalog_entry_id():
    job = _job_row(mode=SCAN_MODE_ENUMERATE, catalog_entry_id=None)
    resp = _job_to_status_response(job)
    assert resp.kind == "enumeration"
    assert resp.parent_job_id is None
    assert resp.shorts_index is None


def test_status_response_enumerate_mode_with_catalog_entry_id():
    """Historical rows still classify as tracking for read compatibility."""
    job = _job_row(
        mode=SCAN_MODE_ENUMERATE,
        catalog_entry_id=uuid4(),
        render_job_id=uuid4(),
    )
    resp = _job_to_status_response(job)
    assert resp.kind == "tracking"
    assert resp.render_job_id == job.render_job_id


def test_status_response_scan_order_mode_kind_and_render_job_id_masked():
    job = _job_row(
        mode=SCAN_MODE_SCAN_ORDER,
        catalog_entry_id=None,
        render_job_id=uuid4(),
    )
    resp = _job_to_status_response(job)
    assert resp.kind == "scan_order"
    assert resp.render_job_id is None


def test_status_response_render_child_mode_lineage_populated():
    parent_id = uuid4()
    job = _job_row(
        mode=SCAN_MODE_RENDER_CHILD,
        parent_job_id=parent_id,
        shorts_index=3,
        render_job_id=uuid4(),
    )
    resp = _job_to_status_response(job)
    assert resp.kind == "render_child"
    assert resp.parent_job_id == parent_id
    assert resp.shorts_index == 3
    assert resp.render_job_id == job.render_job_id


def test_status_response_unknown_mode_raises():
    job = _job_row(mode="banana")
    with pytest.raises(ValueError, match="unknown ProductScanJob.mode"):
        _job_to_status_response(job)


@pytest.mark.asyncio
async def test_find_recent_duplicate_filters_on_org_id():
    from app.modules.shorts_auto_product.repositories.job import (
        ProductScanJobRepository,
    )

    captured_stmt = []

    class _StubResult:
        def scalar_one_or_none(self):
            return None

    async def _stub_execute(stmt):
        captured_stmt.append(stmt)
        return _StubResult()

    fake_session = MagicMock()
    fake_session.execute = AsyncMock(side_effect=_stub_execute)

    repo = ProductScanJobRepository(fake_session)
    await repo.find_recent_duplicate(
        org_id=uuid4(),
        video_id=uuid4(),
        user_id=uuid4(),
        catalog_entry_id=None,
        within_seconds=60,
    )

    rendered = str(
        captured_stmt[0].compile(compile_kwargs={"literal_binds": False})
    )
    assert "org_id" in rendered


def _build_complete_app(monkeypatch, *, job, persisted_catalog_count=0):
    from app.config import Settings, get_settings
    from app.dependencies import get_db_session, verify_internal_token
    from app.modules.shorts_auto_product.internal_router import (
        router as internal_router,
    )

    fake_job_repo = MagicMock()
    fake_job_repo.get_internal = AsyncMock(return_value=job)
    fake_job_repo.complete_enumeration = AsyncMock(return_value=job)

    fake_catalog_repo = MagicMock()
    fake_catalog_repo.bulk_insert = AsyncMock(
        return_value=[MagicMock() for _ in range(persisted_catalog_count)]
    )

    fake_catalog_run_repo = MagicMock()
    fake_catalog_run_repo.mark_after_worker_complete = AsyncMock()

    fake_cost_repo = MagicMock()
    fake_cost_repo.add_cost = AsyncMock()

    import app.modules.shorts_auto_product.repositories as repos_pkg
    import app.modules.shorts_auto_product.internal_router as router_module

    for name, fake_factory in [
        ("ProductScanJobRepository", lambda _db: fake_job_repo),
        ("ProductCatalogRepository", lambda _db: fake_catalog_repo),
        ("ProductCatalogRunRepository", lambda _db: fake_catalog_run_repo),
        ("ProductScanDailyCostRepository", lambda _db: fake_cost_repo),
    ]:
        wrapped = MagicMock(side_effect=fake_factory)
        monkeypatch.setattr(repos_pkg, name, wrapped)
        monkeypatch.setattr(router_module, name, wrapped)

    app = FastAPI()
    app.include_router(internal_router)
    fake_db = MagicMock()
    fake_db.commit = AsyncMock()
    app.dependency_overrides[get_db_session] = lambda: fake_db
    app.dependency_overrides[verify_internal_token] = lambda: "test-token"
    app.dependency_overrides[get_settings] = lambda: Settings(
        auto_shorts_product_v2_stt_enum_enabled=True,
        openai_api_key="test-key",
        auto_shorts_product_v2_consolidate_enabled=False,
    )
    app.state.fake_job_repo = fake_job_repo
    return app


def _catalog_entry_payload():
    return {
        "canonical_crop_s3_key": "products/x/y/abc.jpg",
        "canonical_video_id": str(uuid4()),
        "canonical_frame_idx": 100,
        "canonical_bbox": {"x": 10, "y": 20, "w": 100, "h": 150},
        "llm_label": "테스트 상품",
        "siglip2_embedding": [0.1] * 768,
        "enumeration_confidence": 0.95,
        "prominence_score": 0.8,
        "enumeration_version": "v1.0",
        "enumeration_prompt_version": "v1.0",
        "enumeration_source": "vision",
    }


def test_complete_enumeration_schedules_stt_augment(monkeypatch):
    job_id = uuid4()
    org_id = uuid4()
    video_id = uuid4()
    job = _job_row(job_id=job_id, mode=SCAN_MODE_ENUMERATE)
    job.claimed_by = "test-worker"
    job.org_id = org_id
    job.video_id = video_id

    app = _build_complete_app(
        monkeypatch, job=job, persisted_catalog_count=1,
    )

    stt_mock = MagicMock()
    monkeypatch.setattr(
        "app.modules.shorts_auto_product.enumerate_stt.service."
        "schedule_stt_enumeration_task",
        stt_mock,
    )

    client = TestClient(app)
    resp = client.post(
        f"/internal/products/{job_id}/complete",
        json={
            "claimed_by": "test-worker",
            "cost_delta_usd": "0",
            "catalog_entries": [_catalog_entry_payload()],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200, resp.text

    stt_mock.assert_called_once()
    kwargs = stt_mock.call_args.kwargs
    assert kwargs["org_id"] == org_id
    assert kwargs["video_db_id"] == video_id
    assert kwargs["mode"] == "augment"
    assert kwargs["video_drive_id"] is None


@pytest.mark.parametrize(
    ("mode", "catalog_entry_id"),
    [
        (SCAN_MODE_SCAN_ORDER, None),
        (SCAN_MODE_ENUMERATE, uuid4()),
        (SCAN_MODE_RENDER_CHILD, None),
    ],
)
def test_complete_rejects_retired_tracker_callback(
    monkeypatch, mode, catalog_entry_id,
):
    job_id = uuid4()
    job = _job_row(
        job_id=job_id,
        mode=mode,
        catalog_entry_id=catalog_entry_id,
    )
    job.claimed_by = "test-worker"
    job.org_id = uuid4()
    job.video_id = uuid4()

    app = _build_complete_app(monkeypatch, job=job)
    client = TestClient(app)
    resp = client.post(
        f"/internal/products/{job_id}/complete",
        json={
            "claimed_by": "test-worker",
            "cost_delta_usd": "0",
            "appearances": [{
                "catalog_entry_id": str(uuid4()),
                "scene_id": "scene_001",
                "window_start_ms": 1000,
                "window_end_ms": 5000,
                "avg_bbox_area_pct": 0.2,
                "avg_confidence": 0.9,
                "tracker_version": "v1",
            }],
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 410
    assert "retired" in resp.text
    app.state.fake_job_repo.complete_enumeration.assert_not_awaited()


def test_fail_enumeration_schedules_stt_recover(monkeypatch):
    from app.config import Settings, get_settings
    from app.dependencies import get_db_session, verify_internal_token
    from app.modules.shorts_auto_product.internal_router import (
        router as internal_router,
    )

    job_id = uuid4()
    org_id = uuid4()
    video_id = uuid4()
    failed_job = _job_row(job_id=job_id, mode=SCAN_MODE_ENUMERATE)
    failed_job.org_id = org_id
    failed_job.video_id = video_id

    fake_job_repo = MagicMock()
    fake_job_repo.fail = AsyncMock(return_value=failed_job)
    fake_cost_repo = MagicMock()
    fake_cost_repo.add_cost = AsyncMock()

    import app.modules.shorts_auto_product.repositories as repos_pkg
    import app.modules.shorts_auto_product.internal_router as router_module
    for name, fake_factory in [
        ("ProductScanJobRepository", lambda _db: fake_job_repo),
        ("ProductScanDailyCostRepository", lambda _db: fake_cost_repo),
    ]:
        wrapped = MagicMock(side_effect=fake_factory)
        monkeypatch.setattr(repos_pkg, name, wrapped)
        monkeypatch.setattr(router_module, name, wrapped)

    stt_mock = MagicMock()
    monkeypatch.setattr(
        "app.modules.shorts_auto_product.enumerate_stt.service."
        "schedule_stt_enumeration_task",
        stt_mock,
    )

    app = FastAPI()
    app.include_router(internal_router)
    fake_db = MagicMock()
    fake_db.commit = AsyncMock()
    app.dependency_overrides[get_db_session] = lambda: fake_db
    app.dependency_overrides[verify_internal_token] = lambda: "test-token"
    app.dependency_overrides[get_settings] = lambda: Settings(
        auto_shorts_product_v2_stt_enum_enabled=True,
        openai_api_key="test-key",
        auto_shorts_product_v2_consolidate_enabled=False,
    )

    client = TestClient(app)
    resp = client.post(
        f"/internal/products/{job_id}/fail",
        json={
            "claimed_by": "test-worker",
            "error_code": "llm_timeout",
            "error_message": "openai timeout after 90s",
            "cost_delta_usd": "0",
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 204, resp.text

    stt_mock.assert_called_once()
    kwargs = stt_mock.call_args.kwargs
    assert kwargs["org_id"] == org_id
    assert kwargs["video_db_id"] == video_id
    assert kwargs["mode"] == "recover"


def test_fail_render_child_does_not_schedule_stt(monkeypatch):
    from app.dependencies import get_db_session, verify_internal_token
    from app.modules.shorts_auto_product.internal_router import (
        router as internal_router,
    )

    job_id = uuid4()
    failed_job = _job_row(job_id=job_id, mode=SCAN_MODE_RENDER_CHILD)
    failed_job.org_id = uuid4()
    failed_job.video_id = uuid4()

    fake_job_repo = MagicMock()
    fake_job_repo.fail = AsyncMock(return_value=failed_job)
    fake_cost_repo = MagicMock()
    fake_cost_repo.add_cost = AsyncMock()

    import app.modules.shorts_auto_product.repositories as repos_pkg
    import app.modules.shorts_auto_product.internal_router as router_module
    for name, fake_factory in [
        ("ProductScanJobRepository", lambda _db: fake_job_repo),
        ("ProductScanDailyCostRepository", lambda _db: fake_cost_repo),
    ]:
        wrapped = MagicMock(side_effect=fake_factory)
        monkeypatch.setattr(repos_pkg, name, wrapped)
        monkeypatch.setattr(router_module, name, wrapped)

    stt_mock = MagicMock()
    monkeypatch.setattr(
        "app.modules.shorts_auto_product.enumerate_stt.service."
        "schedule_stt_enumeration_task",
        stt_mock,
    )

    app = FastAPI()
    app.include_router(internal_router)
    fake_db = MagicMock()
    fake_db.commit = AsyncMock()
    app.dependency_overrides[get_db_session] = lambda: fake_db
    app.dependency_overrides[verify_internal_token] = lambda: "test-token"

    client = TestClient(app)
    resp = client.post(
        f"/internal/products/{job_id}/fail",
        json={
            "claimed_by": "test-worker",
            "error_code": "render_enqueue_failed",
            "error_message": "render failed",
            "cost_delta_usd": "0",
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 204, resp.text
    stt_mock.assert_not_called()
