"""Unit tests for the shared Pattern B internal-auth helper.

Covers ``app.lib.internal_auth.resolve_resource_with_org`` directly
(no FastAPI in the loop). Each module's internal_router has its own
integration tests; this file pins the helper's contract so the
mismatch-returns-404 behavior can't regress during refactors.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.lib.internal_auth import resolve_resource_with_org


@dataclass
class _FakeResource:
    """Minimal stand-in for a repo row — only ``org_id`` matters."""
    id: UUID
    org_id: UUID


def _make_lookup(resource: _FakeResource | None):
    """Build an async lookup_fn that returns the given resource."""
    async def _lookup(resource_id: UUID):
        return resource
    return _lookup


# ---------- happy paths ----------


@pytest.mark.asyncio
async def test_returns_resource_and_org_when_header_omitted():
    resource_id = uuid4()
    org_id = uuid4()
    resource = _FakeResource(id=resource_id, org_id=org_id)

    out, derived_org = await resolve_resource_with_org(
        resource_id=resource_id,
        x_heimdex_org_id=None,
        lookup_fn=_make_lookup(resource),
    )
    assert out is resource
    assert derived_org == org_id


@pytest.mark.asyncio
async def test_returns_resource_and_org_when_header_matches():
    resource_id = uuid4()
    org_id = uuid4()
    resource = _FakeResource(id=resource_id, org_id=org_id)

    out, derived_org = await resolve_resource_with_org(
        resource_id=resource_id,
        x_heimdex_org_id=str(org_id),  # matches resource
        lookup_fn=_make_lookup(resource),
    )
    assert out is resource
    assert derived_org == org_id


# ---------- 404s ----------


@pytest.mark.asyncio
async def test_404_when_lookup_returns_none():
    with pytest.raises(HTTPException) as excinfo:
        await resolve_resource_with_org(
            resource_id=uuid4(),
            x_heimdex_org_id=None,
            lookup_fn=_make_lookup(None),
        )
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_404_when_header_mismatches_resource_org():
    """Cross-validation: caller asserts an org that doesn't match
    the resource's org. Response MUST be 404 (not 403, not 422) so
    timing doesn't leak the resource's true tenant."""
    resource_id = uuid4()
    resource_org = uuid4()
    asserted_org = uuid4()
    resource = _FakeResource(id=resource_id, org_id=resource_org)

    with pytest.raises(HTTPException) as excinfo:
        await resolve_resource_with_org(
            resource_id=resource_id,
            x_heimdex_org_id=str(asserted_org),
            lookup_fn=_make_lookup(resource),
        )
    assert excinfo.value.status_code == 404
    # PINNED — flipping this to 403/422 reintroduces the timing leak.
    # Codex F1 fix.
    assert excinfo.value.status_code != 403


@pytest.mark.asyncio
async def test_uses_custom_not_found_detail():
    """Module-specific error text must reach the response so
    operators can distinguish ``channel not found`` from
    ``video not found`` in logs."""
    with pytest.raises(HTTPException) as excinfo:
        await resolve_resource_with_org(
            resource_id=uuid4(),
            x_heimdex_org_id=None,
            lookup_fn=_make_lookup(None),
            not_found_detail="channel not found",
        )
    assert excinfo.value.detail == "channel not found"


# ---------- 400 on malformed header ----------


@pytest.mark.asyncio
async def test_400_when_header_is_not_a_valid_uuid():
    """Header was sent but is malformed (e.g., 'not-a-uuid'). 400
    is correct — this is a client error, distinct from cross-tenant
    mismatch (which is 404). The two error codes intentionally
    diverge."""
    with pytest.raises(HTTPException) as excinfo:
        await resolve_resource_with_org(
            resource_id=uuid4(),
            x_heimdex_org_id="not-a-uuid",
            lookup_fn=_make_lookup(_FakeResource(id=uuid4(), org_id=uuid4())),
        )
    assert excinfo.value.status_code == 400
    assert "X-Heimdex-Org-Id" in excinfo.value.detail


# ---------- helper does not call lookup if header malformed ----------


@pytest.mark.asyncio
async def test_helper_short_circuits_on_malformed_header_before_lookup():
    """A malformed header should fail with 400 before the lookup
    even runs — saves a DB hit on every garbage request."""
    lookup_called = {"yes": False}

    async def _lookup(_id):
        lookup_called["yes"] = True
        return _FakeResource(id=uuid4(), org_id=uuid4())

    with pytest.raises(HTTPException):
        await resolve_resource_with_org(
            resource_id=uuid4(),
            x_heimdex_org_id="garbage",
            lookup_fn=_lookup,
        )
    assert lookup_called["yes"] is False
