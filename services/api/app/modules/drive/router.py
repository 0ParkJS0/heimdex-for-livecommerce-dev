import os
from typing import Annotated
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.modules.drive.repository import DriveConnectionRepository, DriveFileRepository, DriveSecretRepository
from app.modules.drive.schemas import (
    DriveConnectionCreate,
    DriveConnectionResponse,
    DriveConnectionUpdate,
    DriveFileListResponse,
    DriveFileResponse,
    DriveSecretCreate,
    DriveSecretResponse,
    DriveStatusResponse,
)
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org

router = APIRouter(prefix="/drive", tags=["drive"])


def _require_drive_enabled() -> None:
    if not get_settings().drive_connector_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Drive connector is not enabled",
        )


PROCESSING_STATUSES = frozenset({"downloading", "transcoding", "processing"})


@router.get("/status", response_model=DriveStatusResponse)
async def get_status(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    settings = get_settings()
    if not settings.drive_connector_enabled:
        return DriveStatusResponse(connected=False)

    conn_repo = DriveConnectionRepository(db)
    file_repo = DriveFileRepository(db)

    connections = await conn_repo.list_by_org(org_ctx.org_id)
    active = next((c for c in connections if c.status == "active"), None)
    if not active:
        return DriveStatusResponse(connected=False)

    counts = await file_repo.count_by_status(org_ctx.org_id)
    last_indexed = await file_repo.latest_indexed_at(org_ctx.org_id)

    total = sum(counts.values())
    indexed = counts.get("indexed", 0)
    failed = counts.get("failed", 0)
    processing = sum(v for k, v in counts.items() if k in PROCESSING_STATUSES)
    pending = counts.get("pending", 0)

    return DriveStatusResponse(
        connected=True,
        connection_status=active.status,
        drive_name=active.drive_name,
        last_sync_at=active.last_sync_at,
        total_files=total,
        indexed=indexed,
        processing=processing,
        pending=pending,
        failed=failed,
        last_indexed_at=last_indexed,
    )


@router.get("/connections", response_model=list[DriveConnectionResponse])
async def list_connections(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn_repo = DriveConnectionRepository(db)
    return await conn_repo.list_by_org(org_ctx.org_id)


@router.post("/connections", response_model=DriveConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: DriveConnectionCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn_repo = DriveConnectionRepository(db)
    return await conn_repo.create(org_ctx.org_id, body)


@router.get("/connections/{connection_id}", response_model=DriveConnectionResponse)
async def get_connection(
    connection_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn_repo = DriveConnectionRepository(db)
    conn = await conn_repo.get_by_id(connection_id, org_ctx.org_id)
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return conn


@router.patch("/connections/{connection_id}", response_model=DriveConnectionResponse)
async def update_connection(
    connection_id: UUID,
    body: DriveConnectionUpdate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn_repo = DriveConnectionRepository(db)
    conn = await conn_repo.update(connection_id, org_ctx.org_id, body)
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return conn


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn_repo = DriveConnectionRepository(db)
    deleted = await conn_repo.delete(connection_id, org_ctx.org_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")


@router.get("/connections/{connection_id}/files", response_model=DriveFileListResponse)
async def list_files(
    connection_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
    processing_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    conn_repo = DriveConnectionRepository(db)
    file_repo = DriveFileRepository(db)
    conn = await conn_repo.get_by_id(connection_id, org_ctx.org_id)
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    files, total = await file_repo.list_by_connection(
        connection_id, org_ctx.org_id, processing_status=processing_status, limit=limit, offset=offset
    )
    return DriveFileListResponse(
        files=[DriveFileResponse.model_validate(f) for f in files],
        total=total,
    )


@router.get("/files/{file_id}", response_model=DriveFileResponse)
async def get_file(
    file_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    file_repo = DriveFileRepository(db)
    f = await file_repo.get_by_id(file_id, org_ctx.org_id)
    if f is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return f


@router.put("/secrets", response_model=DriveSecretResponse, status_code=status.HTTP_200_OK)
async def upsert_secret(
    body: DriveSecretCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    settings = get_settings()
    if not settings.drive_sa_encryption_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="DRIVE_SA_ENCRYPTION_KEY not configured",
        )
    key = bytes.fromhex(settings.drive_sa_encryption_key)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    encrypted_value = aesgcm.encrypt(nonce, body.sa_key_json.encode(), None)

    secret_repo = DriveSecretRepository(db)
    secret = await secret_repo.upsert(
        org_id=org_ctx.org_id,
        encrypted_value=encrypted_value,
        nonce=nonce,
        impersonate_email=body.impersonate_email,
    )
    return secret
