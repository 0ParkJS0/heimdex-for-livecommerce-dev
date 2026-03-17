from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import get_shorts_render_service
from app.modules.auth.service import get_current_user
from app.modules.shorts_render.schemas import (
    RenderJobCreate,
    RenderJobListResponse,
    RenderJobResponse,
)
from app.modules.shorts_render.service import ShortsRenderService
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

router = APIRouter(prefix="/shorts/render", tags=["shorts-render"])


@router.post("", response_model=RenderJobResponse, status_code=status.HTTP_201_CREATED)
async def create_render_job(
    body: RenderJobCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
):
    user_id = cast(UUID, user.id)
    return await service.create_render_job(org_ctx.org_id, user_id, body)


@router.get("", response_model=RenderJobListResponse)
async def list_render_jobs(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    user_id = cast(UUID, user.id)
    return await service.list_render_jobs(org_ctx.org_id, user_id, limit, offset)


@router.get("/{job_id}", response_model=RenderJobResponse)
async def get_render_job(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
):
    return await service.get_render_job(org_ctx.org_id, job_id)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_render_job(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
):
    await service.delete_render_job(org_ctx.org_id, job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
