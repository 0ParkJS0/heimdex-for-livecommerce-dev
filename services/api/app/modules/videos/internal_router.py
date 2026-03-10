from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session, get_scene_opensearch_client
from app.modules.search.scene_client import SceneSearchClient
from app.modules.videos.reprocess_repository import ReprocessRepository

router = APIRouter(prefix="/videos", tags=["videos-internal"])

from app.dependencies import verify_internal_token as _verify_internal_token


@router.delete("/{video_id}/scenes")
async def delete_video_scenes(
    video_id: str,
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    scene_client: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    deleted = await scene_client.delete_scenes_by_video_id(str(org_id), video_id)
    return {"deleted": deleted}


@router.patch("/{video_id}/reprocess/{job_id}/status")
async def update_reprocess_status(
    video_id: str,
    job_id: str,
    status_value: str = Body(..., alias="status"),
    scene_count: int | None = Body(None),
    error: str | None = Body(None),
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    _ = video_id
    repo = ReprocessRepository(db)
    try:
        parsed_job_id = UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid job_id format",
        )

    await repo.update_status(
        parsed_job_id,
        status_value,
        scene_count=scene_count,
        error=error,
    )
    return {"status": "ok"}
