from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orgs.models import Org


class OrgRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, org_id: UUID) -> Org | None:
        result = await self.session.execute(select(Org).where(Org.id == org_id))
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Org | None:
        result = await self.session.execute(select(Org).where(Org.slug == slug))
        return result.scalar_one_or_none()

    async def create(self, slug: str, name: str) -> Org:
        org = Org(slug=slug, name=name)
        self.session.add(org)
        await self.session.flush()
        return org

    async def list_all(self, limit: int = 500) -> list[Org]:
        result = await self.session.execute(select(Org).limit(limit))
        return list(result.scalars().all())

    async def rotate_agent_api_key(self, org_id: UUID, new_key: str) -> Org:
        result = await self.session.execute(select(Org).where(Org.id == org_id))
        org = result.scalar_one_or_none()
        if org is None:
            raise ValueError(f"Org {org_id} not found")
        org.agent_api_key = new_key
        await self.session.flush()
        return org
