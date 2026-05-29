"""API-side tests for the overlay-enumeration-worker migration (S4).

Covers the API edge of moving overlay enumeration into the worker:

* ``ProductScanService._enumeration_mode`` — overlay flag OFF (default)
  yields "vision" (legacy single pass); ON yields "vision+overlay".
* ``publish_product_enumerate_job`` body carries ``enumeration_mode``;
  ``enqueue_scan`` threads the flag-derived mode through (regression:
  flag off => "vision").
* ``_CatalogEntryPayload`` accepts a per-row ``enumeration_source``
  (default "vision" for back-compat; "overlay" allowed) and the
  ``complete`` handler persists ``entry.enumeration_source`` verbatim
  instead of hardcoding "vision".
* Migration 064 widens the enumeration_source CHECK constraint to
  include "overlay" and chains to 063.

Unit-scope (no Postgres / no boto3) — consistent with the rest of the
test_shorts_auto_product_*.py suite. DB CHECK enforcement is deferred
to integration tests like every other catalog migration here.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.modules.shorts_auto_product.service import ProductScanService

# ---------- helpers (mirror test_shorts_auto_product_service.py) ----------


def _settings(**overrides) -> Settings:
    base = {
        "auto_shorts_product_v2_enabled": True,
        "auto_shorts_product_v2_rollout_pct": 100,
        "auto_shorts_product_v2_daily_budget_usd": 50.0,
        "auto_shorts_product_v2_max_concurrent_per_org": 3,
        "auto_shorts_product_v2_max_keyframes_per_video": 60,
        "auto_shorts_product_v2_duration_presets_sec": "30,60,90",
        "auto_shorts_product_v2_enumeration_prompt_version": "v1.0",
        "auto_shorts_product_v2_enumeration_version": "v1.0",
        "auto_shorts_product_v2_tracker_version": "v1.0",
        "auto_shorts_product_v2_scan_idempotency_seconds": 60,
        "auto_shorts_product_v2_callback_base_url": "http://api:8000",
    }
    base.update(overrides)
    return Settings(**base)


def _build_service(settings: Settings) -> ProductScanService:
    session = AsyncMock()
    svc = ProductScanService(session=session, settings=settings)
    svc.catalog_repo = MagicMock()
    svc.catalog_run_repo = MagicMock()
    svc.appearance_repo = MagicMock()
    svc.job_repo = MagicMock()
    svc.cost_repo = MagicMock()
    svc.cost_repo.get_today_cost = AsyncMock(return_value=Decimal("0"))
    svc.job_repo.find_recent_duplicate = AsyncMock(return_value=None)
    svc.job_repo.find_latest_enumeration_for_video = AsyncMock(return_value=None)
    svc.job_repo.count_active_for_org = AsyncMock(return_value=0)
    svc.catalog_repo.get = AsyncMock(return_value=None)
    svc.catalog_run_repo.create_for_scan = AsyncMock()
    svc.catalog_run_repo.latest_for_video = AsyncMock(return_value=None)
    return svc


def _load_migration_064():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "app" / "db" / "migrations" / "versions"
        / "064_add_overlay_enumeration_source.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_migration_064", migration_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# =========================================================================
# _enumeration_mode — flag-derived worker mode
# =========================================================================

def test_enumeration_mode_defaults_to_vision_when_flag_off():
    svc = _build_service(_settings())
    # The flag defaults False in a real Settings — overlay off.
    assert svc.settings.auto_shorts_product_v2_overlay_track_enabled is False
    assert svc._enumeration_mode() == "vision"


def test_enumeration_mode_is_vision_plus_overlay_when_flag_on():
    svc = _build_service(
        _settings(auto_shorts_product_v2_overlay_track_enabled=True)
    )
    assert svc._enumeration_mode() == "vision+overlay"


def test_enumeration_mode_is_overlay_when_parent_enabled():
    svc = _build_service(
        _settings(
            auto_shorts_product_v2_overlay_track_enabled=True,
            auto_shorts_product_v2_overlay_parent_enabled=True,
        )
    )
    assert svc._enumeration_mode() == "overlay"


# =========================================================================
# enqueue_scan threads enumeration_mode into the publish call
# =========================================================================

@pytest.mark.asyncio
async def test_enqueue_scan_publishes_vision_mode_when_flag_off(monkeypatch):
    """Regression: flag off → enumeration_mode="vision" (current
    behavior preserved)."""
    svc = _build_service(_settings())
    fake_job = MagicMock(id=uuid4())
    svc.job_repo.create_enumeration_job = AsyncMock(return_value=fake_job)

    import app.sqs_producer as sqs_producer

    publish = MagicMock()
    # monkeypatch auto-restores the real function after the test so we
    # don't clobber the module attribute for later tests in the run.
    monkeypatch.setattr(
        sqs_producer, "publish_product_enumerate_job", publish,
    )
    await svc.enqueue_scan(
        org_id=uuid4(), video_id=uuid4(), user_id=uuid4(),
        duration_preset_sec=60,
    )
    assert publish.call_args.kwargs["enumeration_mode"] == "vision"


@pytest.mark.asyncio
async def test_enqueue_scan_publishes_vision_plus_overlay_when_flag_on(monkeypatch):
    svc = _build_service(
        _settings(auto_shorts_product_v2_overlay_track_enabled=True)
    )
    fake_job = MagicMock(id=uuid4())
    svc.job_repo.create_enumeration_job = AsyncMock(return_value=fake_job)

    import app.sqs_producer as sqs_producer

    publish = MagicMock()
    monkeypatch.setattr(
        sqs_producer, "publish_product_enumerate_job", publish,
    )
    await svc.enqueue_scan(
        org_id=uuid4(), video_id=uuid4(), user_id=uuid4(),
        duration_preset_sec=60,
    )
    assert publish.call_args.kwargs["enumeration_mode"] == "vision+overlay"


# =========================================================================
# publish_product_enumerate_job body shape carries enumeration_mode
# =========================================================================

def test_publish_body_carries_enumeration_mode(monkeypatch):
    import app.sqs_producer as sqs_producer

    captured: dict = {}

    def fake_publish(queue_name, body, dedup_id):
        captured["body"] = body

    monkeypatch.setattr(sqs_producer, "_publish_required", fake_publish)

    sqs_producer.publish_product_enumerate_job(
        job_id=uuid4(), org_id=uuid4(), video_id=uuid4(),
        requested_by_user_id=uuid4(),
        enumeration_version="v1.0", enumeration_prompt_version="v1.0",
        max_keyframes=60, callback_base_url="http://api:8000",
        enumeration_mode="vision+overlay",
    )
    assert set(captured["body"]).issuperset(
        {"type", "job_id", "org_id", "video_id", "requested_by_user_id"}
    )
    assert "timestamp" not in captured["body"]
    assert "version" not in captured["body"]
    assert captured["body"]["enumeration_mode"] == "vision+overlay"


def test_publish_body_defaults_enumeration_mode_to_vision(monkeypatch):
    """Legacy callers that omit the param still publish "vision"."""
    import app.sqs_producer as sqs_producer

    captured: dict = {}
    monkeypatch.setattr(
        sqs_producer, "_publish_required",
        lambda q, body, d: captured.update(body=body),
    )
    sqs_producer.publish_product_enumerate_job(
        job_id=uuid4(), org_id=uuid4(), video_id=uuid4(),
        requested_by_user_id=uuid4(),
        enumeration_version="v1.0", enumeration_prompt_version="v1.0",
        max_keyframes=60, callback_base_url="http://api:8000",
    )
    assert captured["body"]["enumeration_mode"] == "vision"


def test_publish_rejects_invalid_enumeration_mode(monkeypatch):
    import app.sqs_producer as sqs_producer

    publish = MagicMock()
    monkeypatch.setattr(sqs_producer, "_publish_required", publish)

    with pytest.raises(ValueError):
        sqs_producer.publish_product_enumerate_job(
            job_id=uuid4(), org_id=uuid4(), video_id=uuid4(),
            requested_by_user_id=uuid4(),
            enumeration_version="v1.0", enumeration_prompt_version="v1.0",
            max_keyframes=60, callback_base_url="http://api:8000",
            enumeration_mode="bad-mode",
        )
    publish.assert_not_called()


# =========================================================================
# _CatalogEntryPayload — per-row enumeration_source
# =========================================================================

def test_catalog_payload_defaults_source_to_vision():
    from app.modules.shorts_auto_product.internal_router import (
        _CatalogEntryPayload,
    )

    payload = _CatalogEntryPayload(
        canonical_crop_s3_key="products/x.jpg",
        canonical_video_id=uuid4(),
        canonical_frame_idx=0,
        canonical_bbox={"x": 0, "y": 0, "w": 10, "h": 10},
        llm_label="세럼",
        siglip2_embedding=[0.0] * 768,
        enumeration_confidence=0.5,
        prominence_score=0.5,
        enumeration_version="v1.0",
        enumeration_prompt_version="v1.0",
        # enumeration_source intentionally omitted — back-compat default.
    )
    assert payload.enumeration_source == "vision"


def test_catalog_payload_accepts_overlay_source():
    from app.modules.shorts_auto_product.internal_router import (
        _CatalogEntryPayload,
    )

    payload = _CatalogEntryPayload(
        canonical_crop_s3_key="products/x.jpg",
        canonical_video_id=uuid4(),
        canonical_frame_idx=0,
        canonical_bbox={"x": 0, "y": 0, "w": 10, "h": 10},
        llm_label="세럼",
        siglip2_embedding=[0.0] * 768,
        enumeration_confidence=0.5,
        prominence_score=0.5,
        enumeration_version="overlay-v0.1",
        enumeration_prompt_version="v2",
        enumeration_source="overlay",
    )
    assert payload.enumeration_source == "overlay"


def test_complete_handler_persists_payload_source_not_hardcoded():
    """The ``complete`` enumeration branch must read
    ``entry.enumeration_source`` (not a hardcoded "vision"). Guard the
    source string so a future edit doesn't re-introduce the hardcode."""
    import inspect

    from app.modules.shorts_auto_product import internal_router

    src = inspect.getsource(internal_router.complete)
    assert '"enumeration_source": entry.enumeration_source' in src
    assert '"enumeration_source": "vision"' not in src


# =========================================================================
# Migration 064 metadata + CHECK widening
# =========================================================================

def test_migration_064_revision_and_down_revision():
    m = _load_migration_064()
    assert m.revision == "064_add_overlay_enumeration_source"
    # Wrong down_revision = silent skip on `alembic upgrade head`.
    assert m.down_revision == "063_add_tangibility_to_video_summaries"


def test_migration_064_upgrade_widens_check_to_include_overlay():
    m = _load_migration_064()
    assert "overlay" in m._WIDE_SET
    # Every prior value survives — widening, not replacing.
    for src in ("vision", "stt", "stt_xref", "manifest", "hybrid"):
        assert src in m._WIDE_SET
    assert m._CHECK_CONSTRAINT_NAME == "ck_product_catalog_enumeration_source"


def test_migration_064_downgrade_narrows_back_without_overlay():
    m = _load_migration_064()
    assert "overlay" not in m._NARROW_SET
    for src in ("vision", "stt", "stt_xref", "manifest", "hybrid"):
        assert src in m._NARROW_SET
