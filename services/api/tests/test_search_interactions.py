from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.search.models import SearchInteraction
from app.modules.search.router import (
    _build_metadata,
    _record_search_event,
    record_interactions,
)
from app.modules.search.schemas import (
    InteractionItem,
    SearchFilters,
    SearchInteractionRequest,
    SearchRequest,
)
from app.modules.search.search_interaction_repository import (
    SearchInteractionRepository,
)


def _load_migration_067():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "db"
        / "migrations"
        / "versions"
        / "067_create_search_interactions.py"
    )
    spec = importlib.util.spec_from_file_location("_migration_067", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigration067Chain:
    def test_revision_and_down_revision(self):
        m = _load_migration_067()
        assert m.revision == "067_create_search_interactions"
        # Wrong down_revision = silent skip on `alembic upgrade head`.
        assert m.down_revision == "066_widen_scan_order_duration_preset_check"


class TestSearchInteractionModel:
    def test_tablename(self):
        assert SearchInteraction.__tablename__ == "search_interactions"

    def test_composite_pk(self):
        pk_cols = [c.name for c in SearchInteraction.__table__.primary_key]
        assert "id" in pk_cols
        assert "created_at" in pk_cols

    def test_metadata_column_name(self):
        col = SearchInteraction.__table__.c["metadata"]
        assert col is not None

    def test_search_event_id_is_not_a_foreign_key(self):
        # Plain BIGINT by design — the parent search_events is partitioned with a
        # composite PK, so no single-column FK is possible (join is done in BQ).
        col = SearchInteraction.__table__.c["search_event_id"]
        assert col.foreign_keys == set()
        assert col.nullable is True


class TestSearchInteractionRepository:
    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.add = MagicMock()
        session.add_all = MagicMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session):
        return SearchInteractionRepository(mock_session)

    @pytest.mark.asyncio
    async def test_create_adds_interaction(self, repo, mock_session):
        org_id = uuid4()
        user_id = uuid4()

        await repo.create(
            org_id=org_id,
            user_id=user_id,
            event_type="click",
            search_event_id=123,
            result_position=2,
            scene_id="vid_scene_001",
            video_id="vid",
            content_type="video",
            dwell_ms=1500,
            metadata={"search_mode": "lexical"},
        )

        mock_session.add.assert_called_once()
        interaction = mock_session.add.call_args[0][0]
        assert isinstance(interaction, SearchInteraction)
        assert interaction.org_id == org_id
        assert interaction.user_id == user_id
        assert interaction.event_type == "click"
        assert interaction.search_event_id == 123
        assert interaction.result_position == 2
        assert interaction.scene_id == "vid_scene_001"
        assert interaction.video_id == "vid"
        assert interaction.content_type == "video"
        assert interaction.dwell_ms == 1500
        assert interaction.metadata_ == {"search_mode": "lexical"}

    @pytest.mark.asyncio
    async def test_create_defaults_metadata_to_empty_dict(self, repo, mock_session):
        await repo.create(
            org_id=uuid4(),
            user_id=uuid4(),
            event_type="impression",
        )
        interaction = mock_session.add.call_args[0][0]
        assert interaction.metadata_ == {}
        assert interaction.search_event_id is None

    @pytest.mark.asyncio
    async def test_create_many_bulk_inserts(self, repo, mock_session):
        org_id = uuid4()
        user_id = uuid4()
        rows = [
            {
                "org_id": org_id,
                "user_id": user_id,
                "event_type": "impression",
                "search_event_id": 7,
                "result_position": i,
                "scene_id": f"scene_{i}",
                "video_id": "vid",
            }
            for i in range(3)
        ]

        count = await repo.create_many(rows)

        assert count == 3
        mock_session.add_all.assert_called_once()
        objs = mock_session.add_all.call_args[0][0]
        assert len(objs) == 3
        assert all(isinstance(o, SearchInteraction) for o in objs)
        assert objs[1].result_position == 1
        assert objs[1].metadata_ == {}

    @pytest.mark.asyncio
    async def test_ensure_partitions_creates_correct_count(self, repo, mock_session):
        partitions = await repo.ensure_partitions(months_ahead=2)
        assert len(partitions) == 3
        assert all(p.startswith("search_interactions_") for p in partitions)

    @pytest.mark.asyncio
    async def test_ensure_partitions_format(self, repo, mock_session):
        partitions = await repo.ensure_partitions(months_ahead=0)
        assert len(partitions) == 1
        now = datetime.now(UTC)
        expected = f"search_interactions_{now.year}_{now.month:02d}"
        assert partitions[0] == expected

    @pytest.mark.asyncio
    async def test_ensure_partitions_executes_ddl(self, repo, mock_session):
        await repo.ensure_partitions(months_ahead=1)
        assert mock_session.execute.call_count == 2
        for call in mock_session.execute.call_args_list:
            sql = str(call[0][0].text)
            assert "CREATE TABLE IF NOT EXISTS" in sql
            assert "PARTITION OF search_interactions" in sql


class TestBuildMetadataContentTypes:
    def test_includes_content_types(self):
        req = SearchRequest(q="x", filters=SearchFilters(content_types=["image"]))
        meta = _build_metadata(req)
        assert meta["content_types"] == ["image"]

    def test_defaults_to_video(self):
        meta = _build_metadata(SearchRequest(q="x"))
        assert meta["content_types"] == ["video"]


def _mock_savepoint(mock_session: AsyncMock) -> MagicMock:
    """Make ``session.begin_nested()`` behave as a no-op SAVEPOINT context
    manager: usable under ``async with`` and NOT suppressing exceptions."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=cm)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin_nested = MagicMock(return_value=cm)
    return cm


class TestRecordSearchEventReturnsId:
    @pytest.mark.asyncio
    async def test_returns_created_event_id(self):
        mock_session = AsyncMock()
        _mock_savepoint(mock_session)
        with patch(
            "app.modules.search.search_event_repository.SearchEventRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.create = AsyncMock(return_value=MagicMock(id=4242))
            mock_repo_cls.return_value = mock_repo

            result = await _record_search_event(
                session=mock_session,
                org_id=uuid4(),
                user_id=uuid4(),
                query_text="t",
                search_mode="lexical",
                result_count=1,
                response_ms=10,
            )
            assert result == 4242
            # Commit is owned by get_db_session; the helper must not commit.
            mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none_and_rolls_back_on_failure(self):
        mock_session = AsyncMock()
        _mock_savepoint(mock_session)
        with patch(
            "app.modules.search.search_event_repository.SearchEventRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.create = AsyncMock(side_effect=Exception("db error"))
            mock_repo_cls.return_value = mock_repo

            result = await _record_search_event(
                session=mock_session,
                org_id=uuid4(),
                user_id=uuid4(),
                query_text="t",
                search_mode="lexical",
                result_count=None,
                response_ms=None,
            )
            assert result is None
            # Rollback is owned by the SAVEPOINT context manager (begin_nested),
            # not an explicit session.rollback() — the savepoint isolates the
            # failed insert from the surrounding request transaction.
            mock_session.begin_nested.assert_called_once()
            mock_session.rollback.assert_not_called()


class TestRecordInteractionsEndpoint:
    @pytest.mark.asyncio
    async def test_records_batch(self):
        db = AsyncMock()
        db.add_all = MagicMock()
        db.flush = AsyncMock()
        org_ctx = MagicMock(org_id=uuid4())
        user = MagicMock(id=uuid4())
        req = SearchInteractionRequest(
            search_event_id=99,
            results=[
                InteractionItem(
                    event_type="impression",
                    scene_id="s0",
                    video_id="v",
                    result_position=0,
                    content_type="video",
                ),
                InteractionItem(
                    event_type="click",
                    scene_id="s1",
                    video_id="v",
                    result_position=1,
                    content_type="image",
                ),
            ],
        )

        with patch(
            "app.modules.search.router.get_settings",
            return_value=MagicMock(analytics_enabled=True),
        ):
            out = await record_interactions(req, org_ctx=org_ctx, user=user, db=db)

        assert out == {"recorded": 2}
        db.add_all.assert_called_once()
        objs = db.add_all.call_args[0][0]
        assert objs[0].event_type == "impression"
        assert objs[0].search_event_id == 99
        assert objs[1].content_type == "image"

    @pytest.mark.asyncio
    async def test_empty_results_records_zero(self):
        db = AsyncMock()
        out = await record_interactions(
            SearchInteractionRequest(results=[]),
            org_ctx=MagicMock(org_id=uuid4()),
            user=MagicMock(id=uuid4()),
            db=db,
        )
        assert out == {"recorded": 0}
        db.add_all.assert_not_called()


class TestListForExport:
    def _mock_session(self, rows):
        scalars = MagicMock()
        scalars.all.return_value = rows
        result = MagicMock()
        result.scalars.return_value = scalars
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)
        return session

    @pytest.mark.asyncio
    async def test_returns_scalar_rows(self):
        session = self._mock_session(["a", "b"])
        repo = SearchInteractionRepository(session)
        out = await repo.list_for_export(
            date_from=datetime(2026, 6, 1, tzinfo=UTC),
            date_to=datetime(2026, 6, 2, tzinfo=UTC),
            after=None,
            limit=100,
        )
        assert out == ["a", "b"]
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_after_cursor_builds_keyset_query(self):
        session = self._mock_session([])
        repo = SearchInteractionRepository(session)
        await repo.list_for_export(
            date_from=datetime(2026, 6, 1, tzinfo=UTC),
            date_to=datetime(2026, 6, 2, tzinfo=UTC),
            after=(datetime(2026, 6, 1, 12, tzinfo=UTC), 5),
            limit=100,
        )
        stmt = session.execute.call_args[0][0]
        sql = str(stmt.compile()).upper()
        assert "SEARCH_INTERACTIONS" in sql
        assert "ORDER BY" in sql
        # Keyset predicate uses the (created_at, id) tuple.
        assert "CREATED_AT" in sql and "ID" in sql
