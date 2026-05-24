from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EditorProject


class EditorProjectRepository:
    """Single-row-per-(user, video) repository. The PUT endpoint upserts
    via ``get_by_video`` + write so we never end up with two projects
    for the same operator viewing the same video."""

    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def get_by_video(
        self, *, org_id: UUID, user_id: UUID, video_id: str
    ) -> EditorProject | None:
        result = await self.session.execute(
            select(EditorProject).where(
                EditorProject.org_id == org_id,
                EditorProject.user_id == user_id,
                EditorProject.video_id == video_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        video_id: str,
        title: str,
        state_json: dict[str, Any],
        schema_version: int,
    ) -> EditorProject:
        existing = await self.get_by_video(
            org_id=org_id, user_id=user_id, video_id=video_id
        )
        if existing is not None:
            existing.title = title
            existing.state_json = state_json
            existing.schema_version = schema_version
            await self.session.flush()
            return existing

        project = EditorProject(
            org_id=org_id,
            user_id=user_id,
            video_id=video_id,
            title=title,
            state_json=state_json,
            schema_version=schema_version,
        )
        self.session.add(project)
        await self.session.flush()
        return project

    async def delete_by_video(
        self, *, org_id: UUID, user_id: UUID, video_id: str
    ) -> bool:
        existing = await self.get_by_video(
            org_id=org_id, user_id=user_id, video_id=video_id
        )
        if existing is None:
            return False
        await self.session.delete(existing)
        await self.session.flush()
        return True
