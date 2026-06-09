"""Tests for the ensure_partitions cron CLI's orchestration logic."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cli import ensure_partitions as cli


def _patch_session_factory():
    """Patch async_sessionmaker so `async with factory() as session` works."""
    session = AsyncMock()
    acm = AsyncMock()
    acm.__aenter__.return_value = session
    acm.__aexit__.return_value = False
    factory = MagicMock(return_value=acm)
    return patch(
        "sqlalchemy.ext.asyncio.async_sessionmaker", return_value=factory
    )


def _repo_returning(created):
    repo = MagicMock()
    repo.ensure_partitions = AsyncMock(return_value=created)
    cls = MagicMock(return_value=repo)
    return cls, repo


class TestEnsurePartitionsRun:
    @pytest.mark.asyncio
    async def test_all_success_returns_zero(self):
        ev_cls, ev = _repo_returning(["search_events_2026_06"])
        it_cls, it = _repo_returning(["search_interactions_2026_06"])
        we_cls, we = _repo_returning(["worker_events_2026_06"])
        with (
            patch("app.db.base.get_async_engine", MagicMock()),
            _patch_session_factory(),
            patch(
                "app.modules.search.search_event_repository.SearchEventRepository",
                ev_cls,
            ),
            patch(
                "app.modules.search.search_interaction_repository.SearchInteractionRepository",
                it_cls,
            ),
            patch("app.modules.worker_events.repository.WorkerEventRepository", we_cls),
        ):
            failures = await cli._run(months_ahead=2)
        assert failures == 0
        for repo in (ev, it, we):
            repo.ensure_partitions.assert_awaited_once_with(months_ahead=2)

    @pytest.mark.asyncio
    async def test_one_failure_does_not_block_others(self):
        ev_cls, ev = _repo_returning(["search_events_2026_06"])
        it_cls, it = _repo_returning([])
        it.ensure_partitions = AsyncMock(side_effect=RuntimeError("boom"))
        we_cls, we = _repo_returning(["worker_events_2026_06"])
        with (
            patch("app.db.base.get_async_engine", MagicMock()),
            _patch_session_factory(),
            patch(
                "app.modules.search.search_event_repository.SearchEventRepository",
                ev_cls,
            ),
            patch(
                "app.modules.search.search_interaction_repository.SearchInteractionRepository",
                it_cls,
            ),
            patch("app.modules.worker_events.repository.WorkerEventRepository", we_cls),
        ):
            failures = await cli._run(months_ahead=2)
        # The interactions repo failed, but the other two still ran.
        assert failures == 1
        ev.ensure_partitions.assert_awaited_once()
        we.ensure_partitions.assert_awaited_once()


class TestEnsurePartitionsMain:
    def test_default_months_ahead(self):
        with patch("sys.argv", ["ensure_partitions"]):
            args = cli._parse_args()
        assert args.months_ahead == cli._DEFAULT_MONTHS_AHEAD

    def test_main_exits_nonzero_on_failure(self):
        with (
            patch.object(cli, "_parse_args", return_value=MagicMock(months_ahead=3)),
            patch.object(cli.asyncio, "run", return_value=2),
            pytest.raises(SystemExit),
        ):
            cli.main()
