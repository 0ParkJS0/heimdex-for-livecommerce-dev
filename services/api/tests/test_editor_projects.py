"""Unit tests for the editor_projects module.

Covers:
* Schema validation (PUT body Pydantic).
* Repository upsert path — mocks AsyncSession at the execute() boundary
  so the test runs in the no-docker allowlist (~ms).
* Repository deletes correctly distinguish hit / miss.

Integration tests against a real Postgres live elsewhere; this file
keeps unit-level coverage of the surface that's most likely to drift
when the schema evolves.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.editor_projects.models import EditorProject
from app.modules.editor_projects.repository import EditorProjectRepository
from app.modules.editor_projects.schemas import (
    EditorProjectResponse,
    EditorProjectUpsert,
)


# ─── Schemas ───────────────────────────────────────────────────────────────


def test_upsert_schema_accepts_arbitrary_state_json() -> None:
    body = EditorProjectUpsert(
        video_id="gd_test_123",
        title="My short",
        state_json={"clips": [], "bookmarks": [{"id": "bm1", "ms": 1500}]},
        schema_version=1,
    )
    assert body.video_id == "gd_test_123"
    assert body.state_json["bookmarks"][0]["id"] == "bm1"


def test_upsert_schema_clamps_title_length() -> None:
    long_title = "x" * 300
    with pytest.raises(ValueError):
        EditorProjectUpsert(
            video_id="v1",
            title=long_title,
            state_json={},
        )


def test_upsert_schema_rejects_negative_schema_version() -> None:
    with pytest.raises(ValueError):
        EditorProjectUpsert(
            video_id="v1",
            title="t",
            state_json={},
            schema_version=0,
        )


# ─── Repository ─────────────────────────────────────────────────────────────


def _make_repo() -> tuple[EditorProjectRepository, AsyncMock]:
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    repo = EditorProjectRepository(session)
    return repo, session


def _execute_result(value: object) -> MagicMock:
    """Mimic the ``await session.execute(...).scalar_one_or_none()`` chain
    that all the repository's selects rely on."""
    chain = MagicMock()
    chain.scalar_one_or_none = MagicMock(return_value=value)
    return chain


@pytest.mark.asyncio
async def test_upsert_creates_new_when_no_existing() -> None:
    repo, session = _make_repo()
    session.execute = AsyncMock(return_value=_execute_result(None))

    project = await repo.upsert(
        org_id=uuid4(),
        user_id=uuid4(),
        video_id="gd_v1",
        title="First save",
        state_json={"clips": []},
        schema_version=1,
    )

    assert isinstance(project, EditorProject)
    # session.add called once with the new model instance.
    session.add.assert_called_once()
    session.flush.assert_awaited()
    assert project.video_id == "gd_v1"
    assert project.title == "First save"


@pytest.mark.asyncio
async def test_upsert_updates_existing_in_place() -> None:
    repo, session = _make_repo()
    existing = EditorProject(
        org_id=uuid4(),
        user_id=uuid4(),
        video_id="gd_v1",
        title="old",
        state_json={"clips": []},
        schema_version=1,
    )
    session.execute = AsyncMock(return_value=_execute_result(existing))

    project = await repo.upsert(
        org_id=existing.org_id,
        user_id=existing.user_id,
        video_id="gd_v1",
        title="new title",
        state_json={"clips": ["c1"]},
        schema_version=2,
    )

    # No new model added — we updated the existing object in place.
    session.add.assert_not_called()
    session.flush.assert_awaited()
    assert project is existing
    assert project.title == "new title"
    assert project.state_json == {"clips": ["c1"]}
    assert project.schema_version == 2


@pytest.mark.asyncio
async def test_delete_returns_false_when_no_row() -> None:
    repo, session = _make_repo()
    session.execute = AsyncMock(return_value=_execute_result(None))
    deleted = await repo.delete_by_video(
        org_id=uuid4(), user_id=uuid4(), video_id="missing"
    )
    assert deleted is False
    session.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_returns_true_when_row_exists() -> None:
    repo, session = _make_repo()
    target = EditorProject(
        org_id=uuid4(),
        user_id=uuid4(),
        video_id="gd_v1",
        title="x",
        state_json={},
        schema_version=1,
    )
    session.execute = AsyncMock(return_value=_execute_result(target))
    deleted = await repo.delete_by_video(
        org_id=target.org_id, user_id=target.user_id, video_id="gd_v1"
    )
    assert deleted is True
    session.delete.assert_awaited_once_with(target)
