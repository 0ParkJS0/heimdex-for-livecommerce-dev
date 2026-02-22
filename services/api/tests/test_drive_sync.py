from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.base import get_db_session
from app.modules.drive.router import router as drive_router
from app.modules.drive.repository import DriveConnectionRepository, DriveFileRepository
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org


def _settings(enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(drive_connector_enabled=enabled)


def _make_connection() -> MagicMock:
    conn = MagicMock()
    conn.id = uuid4()
    conn.org_id = uuid4()
    conn.sync_requested_at = None
    return conn


def _build_drive_app(db: AsyncMock, org_ctx: OrgContext) -> FastAPI:
    app = FastAPI()
    app.include_router(drive_router, prefix="/api")

    async def _mock_get_db_session():
        return db

    async def _mock_get_current_org() -> OrgContext:
        return org_ctx

    app.dependency_overrides[get_db_session] = _mock_get_db_session
    app.dependency_overrides[get_current_org] = _mock_get_current_org
    return app


def test_trigger_sync_sets_flag():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)

    connection_id = uuid4()
    conn = _make_connection()
    conn.sync_requested_at = datetime(2026, 2, 22, 10, 20, 30, tzinfo=timezone.utc)

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(
            DriveConnectionRepository,
            "set_sync_requested",
            AsyncMock(return_value=conn),
        ) as mock_set_sync,
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/api/drive/connections/{connection_id}/sync",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "requested"
    assert payload["sync_requested_at"] == "2026-02-22T10:20:30Z"
    mock_set_sync.assert_awaited_once_with(connection_id, org_ctx.org_id)


def test_trigger_sync_connection_not_found():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)
    connection_id = uuid4()

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(
            DriveConnectionRepository,
            "set_sync_requested",
            AsyncMock(return_value=None),
        ),
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/api/drive/connections/{connection_id}/sync",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == "Connection not found"


def test_trigger_sync_drive_disabled():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(False)),
        patch.object(DriveConnectionRepository, "set_sync_requested", AsyncMock()) as mock_set_sync,
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/api/drive/connections/{uuid4()}/sync",
                headers={"host": "testorg.app.heimdex.local"},
            )

    assert response.status_code == 404
    assert response.json()["detail"] == "Drive connector is not enabled"
    mock_set_sync.assert_not_awaited()
    app.dependency_overrides.clear()


def test_list_folders_empty():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)
    connection_id = uuid4()
    conn = _make_connection()

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(
            DriveConnectionRepository,
            "get_by_id",
            AsyncMock(return_value=conn),
        ),
        patch.object(
            DriveFileRepository,
            "get_folder_stats",
            AsyncMock(return_value=[]),
        ) as mock_get_folder_stats,
    ):
        with TestClient(app) as client:
            response = client.get(
                f"/api/drive/connections/{connection_id}/folders",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"folders": [], "total_files": 0}
    mock_get_folder_stats.assert_awaited_once_with(connection_id, org_ctx.org_id)


def test_list_folders_groups_by_path():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)
    connection_id = uuid4()
    conn = _make_connection()

    folder_stats = [
        {
            "folder_path": "Meeting Videos/2026-02",
            "file_count": 3,
            "indexed_count": 1,
            "processing_count": 1,
            "failed_count": 0,
            "pending_count": 1,
        },
        {
            "folder_path": "쇼츠",
            "file_count": 2,
            "indexed_count": 2,
            "processing_count": 0,
            "failed_count": 0,
            "pending_count": 0,
        },
    ]

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(DriveConnectionRepository, "get_by_id", AsyncMock(return_value=conn)),
        patch.object(
            DriveFileRepository,
            "get_folder_stats",
            AsyncMock(return_value=folder_stats),
        ),
    ):
        with TestClient(app) as client:
            response = client.get(
                f"/api/drive/connections/{connection_id}/folders",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_files"] == 5
    assert len(payload["folders"]) == 2
    assert payload["folders"][0]["folder_path"] == "Meeting Videos/2026-02"
    assert payload["folders"][1]["folder_path"] == "쇼츠"


def test_list_folders_null_path_grouped():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)
    connection_id = uuid4()
    conn = _make_connection()

    folder_stats = [
        {
            "folder_path": "(루트)",
            "file_count": 4,
            "indexed_count": 2,
            "processing_count": 1,
            "failed_count": 0,
            "pending_count": 1,
        }
    ]

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(DriveConnectionRepository, "get_by_id", AsyncMock(return_value=conn)),
        patch.object(
            DriveFileRepository,
            "get_folder_stats",
            AsyncMock(return_value=folder_stats),
        ),
    ):
        with TestClient(app) as client:
            response = client.get(
                f"/api/drive/connections/{connection_id}/folders",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_files"] == 4
    assert payload["folders"][0]["folder_path"] == "(루트)"


def test_list_folders_connection_not_found():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)
    connection_id = uuid4()

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(
            DriveConnectionRepository,
            "get_by_id",
            AsyncMock(return_value=None),
        ),
    ):
        with TestClient(app) as client:
            response = client.get(
                f"/api/drive/connections/{connection_id}/folders",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == "Connection not found"
