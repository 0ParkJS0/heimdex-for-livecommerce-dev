"""Tests for GET /api/drive/source-facts (HQ agent export).

Follows the repo convention of calling the router handler directly with mocked
deps rather than spinning up a TestClient.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.drive.router import get_source_facts
from app.modules.tenancy.context import OrgContext


def _drive_file(video_id: str, *, connection_id, drive_path="sub/a.mp4"):
    return SimpleNamespace(
        video_id=video_id,
        google_file_id=f"gid_{video_id}",
        file_name="a.mp4",
        file_size_bytes=12345,
        md5_checksum="abc123",
        drive_path=drive_path,
        connection_id=connection_id,
    )


def _conn(scope_type="my_drive", drive_name=None, folder_path=None):
    return SimpleNamespace(
        scope_type=scope_type, drive_name=drive_name, folder_path=folder_path
    )


def _settings(enabled: bool):
    return SimpleNamespace(agent_hq_export_enabled=enabled)


@pytest.mark.asyncio
async def test_flag_off_returns_404():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    file_repo = MagicMock()
    file_repo.get_by_video_ids = AsyncMock(return_value={})
    db = AsyncMock()

    with patch("app.modules.drive.router.get_settings", return_value=_settings(False)):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await get_source_facts(
                org_ctx=org_ctx, file_repo=file_repo, db=db, video_ids=["gd_a"]
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_my_drive_assembles_relative_path():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    conn_id = uuid4()
    file_repo = MagicMock()
    file_repo.get_by_video_ids = AsyncMock(
        return_value={"gd_a": _drive_file("gd_a", connection_id=conn_id)}
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=_conn(scope_type="my_drive"))

    with patch("app.modules.drive.router.get_settings", return_value=_settings(True)):
        resp = await get_source_facts(
            org_ctx=org_ctx, file_repo=file_repo, db=db, video_ids=["gd_a"]
        )

    assert len(resp.items) == 1
    item = resp.items[0]
    assert item.video_id == "gd_a"
    assert item.google_file_id == "gid_gd_a"
    assert item.file_size_bytes == 12345
    assert item.md5_checksum == "abc123"
    assert item.mount_relative_path == "My Drive/sub/a.mp4"
    assert resp.missing == []


@pytest.mark.asyncio
async def test_shared_drive_assembles_relative_path():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    conn_id = uuid4()
    file_repo = MagicMock()
    file_repo.get_by_video_ids = AsyncMock(
        return_value={"gd_a": _drive_file("gd_a", connection_id=conn_id, drive_path="x.mp4")}
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=_conn(scope_type="drive", drive_name="Footage"))

    with patch("app.modules.drive.router.get_settings", return_value=_settings(True)):
        resp = await get_source_facts(
            org_ctx=org_ctx, file_repo=file_repo, db=db, video_ids=["gd_a"]
        )
    assert resp.items[0].mount_relative_path == "Shared drives/Footage/x.mp4"


@pytest.mark.asyncio
async def test_missing_video_ids_reported():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    file_repo = MagicMock()
    file_repo.get_by_video_ids = AsyncMock(return_value={})  # nothing in this org
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    with patch("app.modules.drive.router.get_settings", return_value=_settings(True)):
        resp = await get_source_facts(
            org_ctx=org_ctx, file_repo=file_repo, db=db, video_ids=["gd_a", "gd_b"]
        )
    assert resp.items == []
    assert set(resp.missing) == {"gd_a", "gd_b"}


@pytest.mark.asyncio
async def test_org_scoped_lookup():
    """The repo is queried with the caller's org_id (tenant isolation)."""
    org_id = uuid4()
    org_ctx = OrgContext(org_id=org_id, org_slug="testorg")
    file_repo = MagicMock()
    file_repo.get_by_video_ids = AsyncMock(return_value={})
    db = AsyncMock()

    with patch("app.modules.drive.router.get_settings", return_value=_settings(True)):
        await get_source_facts(
            org_ctx=org_ctx, file_repo=file_repo, db=db, video_ids=["gd_a"]
        )
    file_repo.get_by_video_ids.assert_awaited_once_with(org_id, ["gd_a"])


@pytest.mark.asyncio
async def test_connection_fetched_once_per_connection():
    """Two files sharing a connection only hit db.get once."""
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    conn_id = uuid4()
    file_repo = MagicMock()
    file_repo.get_by_video_ids = AsyncMock(
        return_value={
            "gd_a": _drive_file("gd_a", connection_id=conn_id, drive_path="a.mp4"),
            "gd_b": _drive_file("gd_b", connection_id=conn_id, drive_path="b.mp4"),
        }
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=_conn(scope_type="my_drive"))

    with patch("app.modules.drive.router.get_settings", return_value=_settings(True)):
        resp = await get_source_facts(
            org_ctx=org_ctx, file_repo=file_repo, db=db, video_ids=["gd_a", "gd_b"]
        )
    assert len(resp.items) == 2
    assert db.get.await_count == 1
