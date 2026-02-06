from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.logging_config import get_logger
from app.modules.search.client import OpenSearchClient
from app.modules.search.schemas import SearchRequest, SearchResponse
from app.modules.search.service import SearchService
from app.modules.tenancy import OrgContext, get_current_org

logger = get_logger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    db: AsyncSession = Depends(get_db_session),
):
    opensearch = OpenSearchClient()
    try:
        service = SearchService(db, opensearch)
        return await service.search(
            query=request.q,
            org_id=org_ctx.org_id,
            alpha=request.alpha,
            filters=request.filters,
        )
    finally:
        await opensearch.close()
