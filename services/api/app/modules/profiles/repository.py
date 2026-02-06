from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profiles.models import LibraryProfile, ProfileStatus


class LibraryProfileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, profile_id: UUID, org_id: UUID) -> LibraryProfile | None:
        result = await self.session.execute(
            select(LibraryProfile).where(
                LibraryProfile.id == profile_id, LibraryProfile.org_id == org_id
            )
        )
        return result.scalar_one_or_none()

    async def get_active_for_library(self, library_id: UUID, org_id: UUID) -> LibraryProfile | None:
        result = await self.session.execute(
            select(LibraryProfile).where(
                LibraryProfile.library_id == library_id,
                LibraryProfile.org_id == org_id,
                LibraryProfile.status == ProfileStatus.ACTIVE,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        org_id: UUID,
        library_id: UUID,
        segmentation_version: str = "v1",
        embedding_version: str = "v1",
        asr_version: str = "v1",
        face_version: str = "v1",
    ) -> LibraryProfile:
        profile = LibraryProfile(
            org_id=org_id,
            library_id=library_id,
            status=ProfileStatus.BUILDING,
            segmentation_version=segmentation_version,
            embedding_version=embedding_version,
            asr_version=asr_version,
            face_version=face_version,
        )
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def activate(self, profile_id: UUID, org_id: UUID) -> LibraryProfile | None:
        profile = await self.get_by_id(profile_id, org_id)
        if profile:
            profile.status = ProfileStatus.ACTIVE
            profile.activated_at = datetime.now(timezone.utc)
            await self.session.flush()
        return profile
