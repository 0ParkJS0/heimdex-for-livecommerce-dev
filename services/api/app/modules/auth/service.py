from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.logging_config import get_logger
from app.modules.auth.schemas import TokenPayload
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

logger = get_logger(__name__)
security = HTTPBearer(auto_error=False)


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    def create_access_token(
        self,
        user_id: UUID,
        org_id: UUID,
        email: str,
        role: str,
    ) -> str:
        settings = get_settings()
        expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiration_hours)
        
        payload = {
            "sub": str(user_id),
            "org_id": str(org_id),
            "user_id": str(user_id),
            "email": email,
            "role": role,
            "exp": int(expire.timestamp()),
        }
        
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    def decode_token(self, token: str) -> TokenPayload:
        settings = get_settings()
        try:
            payload = jwt.decode(
                token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
            )
            return TokenPayload(**payload)
        except JWTError as e:
            logger.warning("jwt_decode_failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            ) from e


async def get_current_user(
    org_ctx: OrgContext = Depends(get_current_org),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )
    
    auth_service = AuthService(db)
    payload = auth_service.decode_token(credentials.credentials)
    
    if UUID(payload.org_id) != org_ctx.org_id:
        logger.warning(
            "org_mismatch_in_token",
            token_org=payload.org_id,
            request_org=str(org_ctx.org_id),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token organization does not match request",
        )
    
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(UUID(payload.user_id), org_ctx.org_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    return user
