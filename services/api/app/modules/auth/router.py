from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.logging_config import get_logger
from app.modules.auth.schemas import DevLoginRequest, DevLoginResponse
from app.modules.auth.service import AuthService
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.repository import UserRepository

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/dev-login", response_model=DevLoginResponse)
async def dev_login(
    request: DevLoginRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    db: AsyncSession = Depends(get_db_session),
):
    settings = get_settings()
    if settings.environment != "development":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev login only available in development environment",
        )
    
    user_repo = UserRepository(db)
    user = await user_repo.get_by_email(request.email, org_ctx.org_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email {request.email} not found in org {org_ctx.org_slug}",
        )
    
    auth_service = AuthService(db)
    token = auth_service.create_access_token(
        user_id=user.id,
        org_id=org_ctx.org_id,
        email=user.email,
        role=user.role.value,
    )
    
    logger.info("dev_login_success", user_id=str(user.id), org_id=str(org_ctx.org_id))
    
    return DevLoginResponse(
        access_token=token,
        user_id=user.id,
        org_id=org_ctx.org_id,
        org_slug=org_ctx.org_slug,
    )
