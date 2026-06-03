"""PR3 — full-STT shared planner orchestration tests.

Plan: ``.claude/plans/full-stt-shared-planner-2026-05-20.md``

Covers the runner's planner poll + child read-path at the method level
(no real Postgres / OpenSearch / OpenAI). Highest-value checks:

  * Child renders from its persisted plan WITHOUT a picker or OS fetch.
  * NULL / unsupported-version plan → no_render (never render garbage).
  * Planner success → marker cleared (children unlock).
  * Planner unexpected error → marker NOT cleared (lease-expiry retry).
  * Domain "no short possible" → children left NULL, marker still cleared.
  * Same-catalog children collapse to ONE pick_many call.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import app.modules.shorts_auto_product.children.runner as runner_module
from app.modules.shorts_auto_product.children.runner import ChildRunner
from app.modules.shorts_auto_product.track_stt.errors import (
    TranscriptUnavailableError,
)
from app.modules.shorts_auto_product.track_stt.full_stt import (
    FullSttClipPlan,
    FullSttSegment,
    serialize_plan,
)

# ---------- helpers ----------


def _settings_stub():
    s = MagicMock()
    s.auto_shorts_product_v2_child_runner_max_concurrency = 4
    s.auto_shorts_product_v2_child_lease_seconds = 300
    s.auto_shorts_product_v2_full_stt_shared_plan_enabled = True
    s.auto_shorts_product_v2_full_stt_timeout_s = 30.0
    s.auto_shorts_product_v2_full_stt_daily_budget_usd = 5.0
    s.auto_shorts_product_v2_full_stt_model = "gpt-4o-mini"
    s.auto_shorts_product_v2_full_stt_max_scenes = 300
    s.auto_shorts_product_v2_full_stt_live_only = True
    s.auto_shorts_product_v2_purchase_planner_enabled = False
    s.auto_shorts_product_v2_purchase_planner_mode = "contiguous"
    s.openai_api_key = "sk-test"
    s.opensearch_url = "http://localhost:9200"
    return s


def _mock_session_factory():
    @asynccontextmanager
    async def factory():
        session = MagicMock()
        session.commit = AsyncMock()
        yield session

    return factory


def _build_runner(*, settings=None):
    return ChildRunner(
        settings=settings or _settings_stub(),
        session_factory=_mock_session_factory(),
        scene_search_client=MagicMock(),
        instance_id="test-replica",
    )


def _plan(scene_video="gd_test", *, n_segments=3, fallback=False) -> FullSttClipPlan:
    segs = [
        FullSttSegment(
            scene_id=f"{scene_video}_scene_{i:03d}",
            source_start_ms=i * 20_000,
            source_end_ms=(i + 1) * 20_000,
            rationale="r",
        )
        for i in range(n_segments)
    ]
    return FullSttClipPlan(
        segments=segs,
        total_duration_ms=n_segments * 20_000,
        global_rationale="g",
        fallback_used=fallback,
    )


def _lease_stub():
    lease = MagicMock()
    lease.set_stage = MagicMock()
    lease.heartbeat_now = AsyncMock(return_value=True)
    return lease


# ---------- child read-path: _render_child_from_shared_plan ----------


class TestRenderChildFromSharedPlan:
    @pytest.mark.asyncio
    async def test_valid_plan_renders_without_picker_or_os(self, monkeypatch):
        runner = _build_runner()
        render_id = uuid4()
        create_mock = AsyncMock(return_value=render_id)
        monkeypatch.setattr(runner, "_create_render_job", create_mock)
        promote_mock = AsyncMock()
        monkeypatch.setattr(runner, "_try_promote_parent_for_child", promote_mock)
        # _build_os_client must never be called on the shared-plan child path.
        os_guard = MagicMock(side_effect=AssertionError("must not build OS client"))
        monkeypatch.setattr(runner, "_build_os_client", os_guard)

        fake_repo = MagicMock()
        fake_repo.complete_tracking = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(
            runner_module,
            "ProductScanJobRepository",
            MagicMock(return_value=fake_repo),
        )

        child = MagicMock(
            id=uuid4(),
            shorts_index=1,
            full_stt_plan=serialize_plan(_plan("gd_abc")),
        )
        parent = MagicMock(org_id=uuid4(), requested_by_user_id=uuid4())

        await runner._render_child_from_shared_plan(
            child=child,
            parent=parent,
            catalog_label="My product",
            lease=_lease_stub(),
        )

        create_mock.assert_awaited_once()
        assert create_mock.await_args.kwargs["scan_job_id"] == child.id
        assert create_mock.await_args.kwargs["title"] == "My product"
        fake_repo.complete_tracking.assert_awaited_once()
        assert fake_repo.complete_tracking.await_args.kwargs["render_job_id"] == render_id
        promote_mock.assert_awaited_once()
        os_guard.assert_not_called()

    @pytest.mark.asyncio
    async def test_null_plan_routes_to_no_render(self, monkeypatch):
        runner = _build_runner()
        no_render = AsyncMock()
        monkeypatch.setattr(runner, "_complete_no_render", no_render)
        create_mock = AsyncMock()
        monkeypatch.setattr(runner, "_create_render_job", create_mock)

        child = MagicMock(id=uuid4(), shorts_index=1, full_stt_plan=None)
        parent = MagicMock(org_id=uuid4(), requested_by_user_id=uuid4())

        await runner._render_child_from_shared_plan(
            child=child,
            parent=parent,
            catalog_label="X",
            lease=_lease_stub(),
        )
        no_render.assert_awaited_once()
        assert no_render.await_args.kwargs["reason"] == "stt_no_plan"
        create_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsupported_version_routes_to_no_render(self, monkeypatch):
        runner = _build_runner()
        no_render = AsyncMock()
        monkeypatch.setattr(runner, "_complete_no_render", no_render)
        create_mock = AsyncMock()
        monkeypatch.setattr(runner, "_create_render_job", create_mock)

        bad = serialize_plan(_plan("gd_abc"))
        bad["v"] = 999  # unknown schema version
        child = MagicMock(id=uuid4(), shorts_index=1, full_stt_plan=bad)
        parent = MagicMock(org_id=uuid4(), requested_by_user_id=uuid4())

        await runner._render_child_from_shared_plan(
            child=child,
            parent=parent,
            catalog_label="X",
            lease=_lease_stub(),
        )
        no_render.assert_awaited_once()
        assert no_render.await_args.kwargs["reason"] == "stt_plan_version_unsupported"
        create_mock.assert_not_called()


# ---------- planner: _plan_parent marker semantics ----------


class TestPlanParentMarkerSemantics:
    def _patch_claim(self, runner, monkeypatch, *, claimed: bool):
        fake_repo = MagicMock()
        fake_repo.claim_planning_parent = AsyncMock(
            return_value=MagicMock() if claimed else None,
        )
        monkeypatch.setattr(
            runner_module,
            "ProductScanJobRepository",
            MagicMock(return_value=fake_repo),
        )
        return fake_repo

    def _patch_clients(self, runner, monkeypatch):
        fake_os = AsyncMock()
        fake_os.close = AsyncMock()
        monkeypatch.setattr(runner, "_build_os_client", lambda: fake_os)
        import openai

        fake_openai = MagicMock()
        fake_openai.close = AsyncMock()
        monkeypatch.setattr(openai, "AsyncOpenAI", MagicMock(return_value=fake_openai))

    @pytest.mark.asyncio
    async def test_success_clears_marker(self, monkeypatch):
        runner = _build_runner()
        self._patch_claim(runner, monkeypatch, claimed=True)
        self._patch_clients(runner, monkeypatch)

        parent = MagicMock(
            id=uuid4(),
            org_id=uuid4(),
            video_id=uuid4(),
            length_seconds=60,
            duration_preset_sec=None,
            requested_by_user_id=uuid4(),
        )
        cat = uuid4()
        children = [MagicMock(id=uuid4(), shorts_index=i, catalog_entry_id=cat) for i in range(3)]
        monkeypatch.setattr(
            runner,
            "_load_planning_context",
            AsyncMock(return_value=(parent, children, {cat: "Prod"})),
        )
        monkeypatch.setattr(
            runner,
            "_resolve_catalog_for_child",
            MagicMock(return_value=cat),
        )
        group_mock = AsyncMock()
        monkeypatch.setattr(runner, "_plan_one_group", group_mock)
        clear_mock = AsyncMock()
        monkeypatch.setattr(runner, "_clear_planning_marker", clear_mock)

        await runner._plan_parent(parent.id)

        clear_mock.assert_awaited_once_with(parent.id)

    @pytest.mark.asyncio
    async def test_same_catalog_children_collapse_to_one_group(self, monkeypatch):
        runner = _build_runner()
        self._patch_claim(runner, monkeypatch, claimed=True)
        self._patch_clients(runner, monkeypatch)

        parent = MagicMock(
            id=uuid4(),
            org_id=uuid4(),
            video_id=uuid4(),
            length_seconds=60,
            duration_preset_sec=None,
            requested_by_user_id=uuid4(),
        )
        cat = uuid4()
        children = [MagicMock(id=uuid4(), shorts_index=i, catalog_entry_id=cat) for i in range(3)]
        monkeypatch.setattr(
            runner,
            "_load_planning_context",
            AsyncMock(return_value=(parent, children, {cat: "Prod"})),
        )
        monkeypatch.setattr(
            runner,
            "_resolve_catalog_for_child",
            MagicMock(return_value=cat),
        )
        group_mock = AsyncMock()
        monkeypatch.setattr(runner, "_plan_one_group", group_mock)
        monkeypatch.setattr(runner, "_clear_planning_marker", AsyncMock())

        await runner._plan_parent(parent.id)

        # ONE call for the single product, with all three children.
        group_mock.assert_awaited_once()
        assert len(group_mock.await_args.kwargs["group"]) == 3

    @pytest.mark.asyncio
    async def test_lost_claim_does_nothing(self, monkeypatch):
        runner = _build_runner()
        self._patch_claim(runner, monkeypatch, claimed=False)
        load_ctx = AsyncMock()
        monkeypatch.setattr(runner, "_load_planning_context", load_ctx)
        clear_mock = AsyncMock()
        monkeypatch.setattr(runner, "_clear_planning_marker", clear_mock)

        await runner._plan_parent(uuid4())

        load_ctx.assert_not_called()
        clear_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_unexpected_error_does_not_clear_marker(self, monkeypatch):
        """A bug/transient in planning must NOT clear the marker — the
        lease expires and another poll retries. This is the anti-hang
        invariant: children stay gated (retry) rather than no_render.
        """
        runner = _build_runner()
        self._patch_claim(runner, monkeypatch, claimed=True)
        self._patch_clients(runner, monkeypatch)

        parent = MagicMock(
            id=uuid4(),
            org_id=uuid4(),
            video_id=uuid4(),
            length_seconds=60,
            duration_preset_sec=None,
            requested_by_user_id=uuid4(),
        )
        cat = uuid4()
        children = [MagicMock(id=uuid4(), shorts_index=0, catalog_entry_id=cat)]
        monkeypatch.setattr(
            runner,
            "_load_planning_context",
            AsyncMock(return_value=(parent, children, {cat: "Prod"})),
        )
        monkeypatch.setattr(
            runner,
            "_resolve_catalog_for_child",
            MagicMock(return_value=cat),
        )
        monkeypatch.setattr(
            runner,
            "_plan_one_group",
            AsyncMock(side_effect=RuntimeError("OS down")),
        )
        clear_mock = AsyncMock()
        monkeypatch.setattr(runner, "_clear_planning_marker", clear_mock)

        with pytest.raises(RuntimeError):
            await runner._plan_parent(parent.id)
        clear_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_wrapper_swallows_error_and_leaves_marker(self, monkeypatch):
        """``_run_one_planning_parent`` catches the error (loop stays
        alive) and the marker stays set → lease-expiry retry."""
        runner = _build_runner()
        clear_mock = AsyncMock()
        monkeypatch.setattr(runner, "_clear_planning_marker", clear_mock)
        monkeypatch.setattr(
            runner,
            "_plan_parent",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        # Must NOT raise out of the wrapper.
        await runner._run_one_planning_parent(uuid4())
        clear_mock.assert_not_called()


# ---------- planner: _plan_one_group ----------


class TestPlanOneGroup:
    @pytest.mark.asyncio
    async def test_persists_one_plan_per_child(self, monkeypatch):
        runner = _build_runner()
        monkeypatch.setattr(
            runner,
            "_load_stt_inputs",
            AsyncMock(return_value=("gd_abc", "달심", ["이 주스"])),
        )
        plans = [_plan("gd_abc"), _plan("gd_abc", n_segments=4)]
        import app.modules.shorts_auto_product.track_stt.service as stt_service

        monkeypatch.setattr(
            stt_service,
            "plan_full_stt_clips",
            AsyncMock(return_value=plans),
        )
        fake_repo = MagicMock()
        fake_repo.set_child_full_stt_plan = AsyncMock()
        monkeypatch.setattr(
            runner_module,
            "ProductScanJobRepository",
            MagicMock(return_value=fake_repo),
        )

        parent = MagicMock(id=uuid4(), org_id=uuid4(), video_id=uuid4())
        group = [MagicMock(id=uuid4()), MagicMock(id=uuid4())]

        await runner._plan_one_group(
            parent=parent,
            catalog_entry_id=uuid4(),
            group=group,
            target_duration_ms=60_000,
            os_client=AsyncMock(),
            openai_client=MagicMock(),
        )
        assert fake_repo.set_child_full_stt_plan.await_count == 2

    @pytest.mark.asyncio
    async def test_domain_error_persists_nothing(self, monkeypatch):
        runner = _build_runner()
        monkeypatch.setattr(
            runner,
            "_load_stt_inputs",
            AsyncMock(return_value=("gd_abc", "달심", [])),
        )
        import app.modules.shorts_auto_product.track_stt.service as stt_service

        monkeypatch.setattr(
            stt_service,
            "plan_full_stt_clips",
            AsyncMock(side_effect=TranscriptUnavailableError("no transcript")),
        )
        fake_repo = MagicMock()
        fake_repo.set_child_full_stt_plan = AsyncMock()
        monkeypatch.setattr(
            runner_module,
            "ProductScanJobRepository",
            MagicMock(return_value=fake_repo),
        )

        parent = MagicMock(id=uuid4(), org_id=uuid4(), video_id=uuid4())
        group = [MagicMock(id=uuid4())]

        # Must not raise — domain error is swallowed (children left NULL).
        await runner._plan_one_group(
            parent=parent,
            catalog_entry_id=uuid4(),
            group=group,
            target_duration_ms=60_000,
            os_client=AsyncMock(),
            openai_client=MagicMock(),
        )
        fake_repo.set_child_full_stt_plan.assert_not_called()
