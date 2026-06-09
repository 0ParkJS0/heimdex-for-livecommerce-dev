import time
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.dependencies import get_scene_search_service, get_search_service
from app.logging_config import get_logger
from app.modules.auth import get_current_user
from app.modules.search.rate_limit import (
    require_interaction_rate_limit,
    require_search_rate_limit,
)
from app.modules.search.scene_service import SceneSearchService
from app.modules.search.schemas import (
    SceneSearchResponse,
    SearchInteractionRequest,
    SearchRequest,
    VideoSearchResponse,
)
from app.modules.search.search_interaction_repository import (
    SearchInteractionRepository,
)
from app.modules.search.service import SearchService
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

logger = get_logger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


async def _record_search_event(
    *,
    session: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    query_text: str,
    search_mode: str,
    result_count: int | None,
    response_ms: int | None,
    extra_metadata: dict[str, Any] | None = None,
) -> int | None:
    """Record a search event on the request session and return its id.

    Reuses the caller's request-scoped session (the one the search service
    already holds) rather than opening a second one — so a search never holds
    an extra pool connection under concurrency. The request's get_db_session
    owns the commit. The write is wrapped in a SAVEPOINT (begin_nested) so a
    failure rolls back ONLY the event insert, never the surrounding request
    transaction; returns None — analytics must never block search.
    """
    from app.modules.search.search_event_repository import SearchEventRepository

    try:
        async with session.begin_nested():
            repo = SearchEventRepository(session)
            event = await repo.create(
                org_id=org_id,
                user_id=user_id,
                query_text=query_text,
                search_mode=search_mode,
                result_count=result_count,
                response_ms=response_ms,
                metadata=extra_metadata,
            )
        return event.id
    except Exception:
        logger.warning("search_event_recording_failed", exc_info=True)
        return None


def _extract_result_count(response: Any) -> int | None:
    if hasattr(response, "total_candidates"):
        return response.total_candidates
    return None


def _build_metadata(request: SearchRequest) -> dict[str, Any]:
    meta: dict[str, Any] = {"alpha": request.alpha, "group_by": request.group_by}
    if request.filters.date_from:
        meta["date_from"] = request.filters.date_from.isoformat()
    if request.filters.date_to:
        meta["date_to"] = request.filters.date_to.isoformat()
    if request.filters.content_types:
        # "video" | "image" — distinguishes 동영상 검색 vs 이미지 검색 in analytics.
        meta["content_types"] = list(request.filters.content_types)
    if request.filters.source_types:
        meta["source_types"] = list(request.filters.source_types)
    if request.filters.person_cluster_ids:
        meta["person_cluster_ids"] = request.filters.person_cluster_ids
    if request.include_ocr is not None:
        meta["include_ocr"] = request.include_ocr
    if request.color_family:
        meta["color_family"] = request.color_family
    elif request.color_hex:
        meta["color_hex"] = request.color_hex
    if request.page_size is not None:
        meta["page_size_requested"] = request.page_size
    if request.max_per_video is not None:
        meta["max_per_video_requested"] = request.max_per_video
    if request.offset:
        meta["offset"] = request.offset
    settings = get_settings()
    if settings.reranker_enabled:
        meta["reranker_enabled"] = True
    return meta


@router.post("")
async def search(
    request: SearchRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    search_service: SearchService = Depends(get_search_service),
    scene_search_service: SceneSearchService = Depends(get_scene_search_service),
    db: AsyncSession = Depends(get_db_session),
    _rate_limit=Depends(require_search_rate_limit),
):
    """Unified search endpoint.

    Routes to segment or scene search based on ``SEARCH_DEFAULT_MODE``.
    Rollback: flip the env var — no code change needed.
    """
    settings = get_settings()

    logger.debug(
        "search_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
        mode=settings.search_default_mode,
        search_mode=request.search_mode,
    )

    user_id = cast(UUID, user.id)
    t0 = time.monotonic()

    if settings.search_default_mode == "scenes":
        result = await scene_search_service.search(
            query=request.q,
            org_id=org_ctx.org_id,
            alpha=request.alpha,
            filters=request.filters,
            include_ocr=request.include_ocr,
            user_id=user_id,
            group_by=request.group_by,
            search_mode=request.search_mode,
            color_hex=request.color_hex,
            color_family=request.color_family,
            page_size=request.page_size,
            max_per_video=request.max_per_video,
            offset=request.offset,
        )
    else:
        result = await search_service.search(
            query=request.q,
            org_id=org_ctx.org_id,
            alpha=request.alpha,
            filters=request.filters,
            user_id=user_id,
        )

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    search_event_id: int | None = None
    if settings.analytics_enabled:
        t_event = time.monotonic()
        search_event_id = await _record_search_event(
            session=db,
            org_id=org_ctx.org_id,
            user_id=user_id,
            query_text=request.q,
            search_mode=request.search_mode,
            result_count=_extract_result_count(result),
            response_ms=elapsed_ms,
            extra_metadata=_build_metadata(request),
        )
        # event_record_ms = the synchronous cost the event write adds to the
        # search path (INSERT on the already-open request connection). Lets us
        # confirm the await stays negligible next to the OpenSearch round-trip.
        logger.debug(
            "search_event_recorded",
            event_record_ms=int((time.monotonic() - t_event) * 1000),
            search_ms=elapsed_ms,
        )
    # Surface the event id so the client can link interaction events to it.
    if hasattr(result, "search_event_id"):
        result.search_event_id = search_event_id

    return result


@router.post("/interactions", status_code=202)
async def record_interactions(
    request: SearchInteractionRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _rate_limit: Annotated[None, Depends(require_interaction_rate_limit)],
) -> dict[str, int]:
    """Record search-result interactions (impression / click / play_*).

    Batched: a single search-result render posts all impressions at once;
    individual clicks/plays post one item. Returns ``{"recorded": n}``. The
    write shares the request session (commit owned by ``get_db_session``).
    """
    settings = get_settings()
    if not settings.analytics_enabled or not request.results:
        return {"recorded": 0}

    user_id = cast(UUID, user.id)
    repo = SearchInteractionRepository(db)
    rows = [
        {
            "org_id": org_ctx.org_id,
            "user_id": user_id,
            "event_type": item.event_type,
            "search_event_id": request.search_event_id,
            "result_position": item.result_position,
            "scene_id": item.scene_id,
            "video_id": item.video_id,
            "content_type": item.content_type,
            "dwell_ms": item.dwell_ms,
        }
        for item in request.results
    ]
    count = await repo.create_many(rows)
    return {"recorded": count}


@router.post("/scenes", response_model=SceneSearchResponse | VideoSearchResponse)
async def search_scenes(
    request: SearchRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    scene_search_service: SceneSearchService = Depends(get_scene_search_service),
    db: AsyncSession = Depends(get_db_session),
    _rate_limit=Depends(require_search_rate_limit),
):
    """Dedicated scene search endpoint.

    Always returns scene results regardless of ``SEARCH_DEFAULT_MODE``.
    """
    settings = get_settings()
    logger.debug(
        "scene_search_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
        search_mode=request.search_mode,
    )
    user_id = cast(UUID, user.id)
    t0 = time.monotonic()

    result = await scene_search_service.search(
        query=request.q,
        org_id=org_ctx.org_id,
        alpha=request.alpha,
        filters=request.filters,
        include_ocr=request.include_ocr,
        user_id=user_id,
        group_by=request.group_by,
        search_mode=request.search_mode,
        color_hex=request.color_hex,
        color_family=request.color_family,
        page_size=request.page_size,
        max_per_video=request.max_per_video,
        offset=request.offset,
    )

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    search_event_id: int | None = None
    if settings.analytics_enabled:
        t_event = time.monotonic()
        search_event_id = await _record_search_event(
            session=db,
            org_id=org_ctx.org_id,
            user_id=user_id,
            query_text=request.q,
            search_mode=request.search_mode,
            result_count=_extract_result_count(result),
            response_ms=elapsed_ms,
            extra_metadata=_build_metadata(request),
        )
        # event_record_ms = the synchronous cost the event write adds to the
        # search path (INSERT on the already-open request connection). Lets us
        # confirm the await stays negligible next to the OpenSearch round-trip.
        logger.debug(
            "search_event_recorded",
            event_record_ms=int((time.monotonic() - t_event) * 1000),
            search_ms=elapsed_ms,
        )
    # Surface the event id so the client can link interaction events to it.
    if hasattr(result, "search_event_id"):
        result.search_event_id = search_event_id

    return result
