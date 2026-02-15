from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.modules.ingest.auth import verify_agent_token
from app.modules.tenancy.context import OrgContext


def _make_org(*, slug: str = "org-slug", name: str = "Org", agent_api_key: str | None = None) -> MagicMock:
    """Create a mock Org to avoid SQLAlchemy mapper initialization."""
    org = MagicMock()
    org.slug = slug
    org.name = name
    org.agent_api_key = agent_api_key
    return org


class TestPerOrgAgentToken:
    async def _run_verify(
        self,
        *,
        token: str,
        mode: str,
        ingest_enabled: bool = True,
        global_key: str = "global-key",
        org_key: str | None = None,
    ) -> OrgContext:
        org_ctx = OrgContext(org_id=uuid4(), org_slug="org-slug")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = _make_org(agent_api_key=org_key)
        db.execute.return_value = db_result

        settings = MagicMock()
        settings.agent_ingest_enabled = ingest_enabled
        settings.agent_api_key = global_key
        settings.agent_api_key_mode = mode

        with patch("app.modules.ingest.auth.get_settings", return_value=settings):
            return await verify_agent_token(credentials=credentials, org_ctx=org_ctx, db=db)

    @pytest.mark.asyncio
    async def test_per_org_key_valid(self):
        result = await self._run_verify(token="org-key", mode="per-org", org_key="org-key")
        assert isinstance(result, OrgContext)

    @pytest.mark.asyncio
    async def test_per_org_key_wrong(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._run_verify(token="wrong-key", mode="per-org", org_key="org-key")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_per_org_key_cross_org(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._run_verify(token="org-a-key", mode="per-org", org_key="org-b-key")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_per_org_mode_no_key_set(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._run_verify(token="global-key", mode="per-org", org_key=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_global_mode_org_key_set(self):
        result = await self._run_verify(token="org-key", mode="global", org_key="org-key")
        assert isinstance(result, OrgContext)

    @pytest.mark.asyncio
    async def test_global_mode_fallback_to_global(self):
        result = await self._run_verify(
            token="global-key",
            mode="global",
            org_key=None,
            global_key="global-key",
        )
        assert isinstance(result, OrgContext)

    @pytest.mark.asyncio
    async def test_global_mode_global_key_rejected_when_per_org(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._run_verify(
                token="global-key",
                mode="per-org",
                org_key="org-key",
                global_key="global-key",
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_ingest_disabled(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._run_verify(
                token="org-key",
                mode="per-org",
                org_key="org-key",
                ingest_enabled=False,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_empty_token_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._run_verify(token="", mode="per-org", org_key="org-key")
        assert exc_info.value.status_code == 401
