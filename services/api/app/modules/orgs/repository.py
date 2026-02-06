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

    async def list_all(self) -> list[Org]:
        result = await self.session.execute(select(Org))
        return list(result.scalars().all())
