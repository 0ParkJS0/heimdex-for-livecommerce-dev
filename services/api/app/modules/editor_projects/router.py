"""HTTP surface for the editor-projects module.

Wire shape:
  PUT    /api/editor-projects        — upsert (body: {video_id, title, state_json, schema_version})
  GET    /api/editor-projects?video_id=...  — fetch the one row for (user, video) or 404
  DELETE /api/editor-projects?video_id=...  — remove the saved snapshot

The PUT lane is the autosave hot path; the frontend debounces ~1.5s
and also flushes on beforeunload / visibilitychange. The endpoint is
deliberately idempotent — replaying the same body produces the same
state.
"""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies import get_editor_project_repository
from app.modules.auth.service import get_current_user
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

from .models import EditorProject
from .repository import EditorProjectRepository
from .schemas import EditorProjectResponse, EditorProjectUpsert

router = APIRouter(prefix="/editor-projects", tags=["editor-projects"])


def _to_response(project: EditorProject) -> EditorProjectResponse:
    return EditorProjectResponse(
        id=cast(UUID, project.id),
        video_id=project.video_id,
        title=project.title,
        state_json=project.state_json,
        schema_version=project.schema_version,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.put("", response_model=EditorProjectResponse)
async def upsert_editor_project(
    body: EditorProjectUpsert,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[EditorProjectRepository, Depends(get_editor_project_repository)],
):
    project = await repo.upsert(
        org_id=org_ctx.org_id,
        user_id=cast(UUID, user.id),
        video_id=body.video_id,
        title=body.title,
        state_json=body.state_json,
        schema_version=body.schema_version,
    )
    return _to_response(project)


@router.get("", response_model=EditorProjectResponse)
async def get_editor_project(
    video_id: Annotated[str, Query(..., max_length=64)],
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[EditorProjectRepository, Depends(get_editor_project_repository)],
):
    project = await repo.get_by_video(
        org_id=org_ctx.org_id,
        user_id=cast(UUID, user.id),
        video_id=video_id,
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No editor project saved for this video.",
        )
    return _to_response(project)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_editor_project(
    video_id: Annotated[str, Query(..., max_length=64)],
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[EditorProjectRepository, Depends(get_editor_project_repository)],
):
    deleted = await repo.delete_by_video(
        org_id=org_ctx.org_id,
        user_id=cast(UUID, user.id),
        video_id=video_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No editor project to delete for this video.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
