import hmac
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import get_db_session
from app.logging_config import get_logger
from app.modules.face.repository import FaceRepository
from app.modules.face.schemas import (
    FaceIdentityUpsertRequest,
    FaceIdentityUpsertResponse,
    FaceMatchRequest,
    FaceMatchResponse,
    FaceMatchResult,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/internal/face", tags=["internal-face"])


async def _verify_internal_token(
    authorization: str = Header(..., alias="Authorization"),
) -> str:
    """Validate internal Bearer token against DRIVE_INTERNAL_API_KEY."""
    settings = get_settings()

    if not settings.drive_internal_api_key:
        logger.error("drive_internal_api_key_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal face API not configured",
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )

    token = parts[1]
    if not hmac.compare_digest(token, settings.drive_internal_api_key):
        logger.warning("internal_face_invalid_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal API key",
        )

    return token


@router.post("/match", response_model=FaceMatchResponse)
async def internal_face_match(
    request: FaceMatchRequest,
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    if request.org_id != str(org_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request org_id does not match X-Heimdex-Org-Id",
        )

    repository = FaceRepository(db)
    matches = await repository.match_embeddings(
        org_id=org_id,
        embeddings=request.embeddings,
        threshold=request.threshold,
    )

    logger.info(
        "internal_face_match_complete",
        org_id=str(org_id),
        embedding_count=len(request.embeddings),
        matched_count=sum(1 for item in matches if item is not None),
    )

    response_matches: list[FaceMatchResult] = []
    for item in matches:
        if item is None:
            response_matches.append(FaceMatchResult(cluster_id=None, similarity=None))
            continue
        response_matches.append(
            FaceMatchResult(
                cluster_id=item["cluster_id"],
                similarity=item["similarity"],
            )
        )

    return FaceMatchResponse(matches=response_matches)


@router.post("/identities", response_model=FaceIdentityUpsertResponse)
async def internal_face_identities(
    request: FaceIdentityUpsertRequest,
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    if request.org_id != str(org_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request org_id does not match X-Heimdex-Org-Id",
        )

    repository = FaceRepository(db)
    created = 0
    updated = 0

    for item in request.identities:
        is_new, identity_id = await repository.upsert_identity(
            org_id=org_id,
            cluster_id=item.cluster_id,
            embedding=item.embedding,
            quality=item.quality,
            best_thumbnail_video_id=item.video_id,
        )
        await repository.add_exemplar(
            identity_id=identity_id,
            org_id=org_id,
            video_id=item.video_id,
            scene_id=item.scene_id,
            embedding=item.embedding,
            quality=item.quality,
            bbox_json=item.bbox_json,
        )
        if is_new:
            created += 1
        else:
            updated += 1

    logger.info(
        "internal_face_identities_upsert_complete",
        org_id=str(org_id),
        requested=len(request.identities),
        created=created,
        updated=updated,
    )

    return FaceIdentityUpsertResponse(created=created, updated=updated)
