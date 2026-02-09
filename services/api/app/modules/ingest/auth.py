"""
Agent authentication dependency for the ingest endpoint.

Validates a pre-shared API key (Bearer token) and resolves org context
from the Host header. This is separate from user JWT authentication —
agents do not need a user identity, only an org-scoped token.

Security:
- Constant-time comparison via hmac.compare_digest to prevent timing attacks
- Feature flag to disable ingestion entirely (agent_ingest_enabled)
- Org context derived from Host header only (never from client params)
"""
import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org

logger = get_logger(__name__)

_bearer_scheme = HTTPBearer()


async def verify_agent_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    org_ctx: OrgContext = Depends(get_current_org),
) -> OrgContext:
    """
    Validate agent Bearer token and return resolved org context.

    Checks:
    1. agent_ingest_enabled feature flag is True
    2. Bearer token matches the configured agent_api_key (constant-time)
    3. Org resolved from Host header via TenancyMiddleware

    Returns:
        OrgContext with org_id and org_slug from the Host header.

    Raises:
        HTTPException 403: If ingestion is disabled.
        HTTPException 401: If the token is invalid.
    """
    settings = get_settings()

    if not settings.agent_ingest_enabled:
        logger.warning("agent_ingest_disabled", org_slug=org_ctx.org_slug)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent ingestion is disabled",
        )

    if not hmac.compare_digest(credentials.credentials, settings.agent_api_key):
        logger.warning(
            "agent_ingest_invalid_token",
            org_slug=org_ctx.org_slug,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid agent API key",
        )

    logger.debug(
        "agent_token_verified",
        org_id=str(org_ctx.org_id),
        org_slug=org_ctx.org_slug,
    )
    return org_ctx
