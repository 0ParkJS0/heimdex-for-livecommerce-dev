from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass
class OrgContext:
    org_id: UUID
    org_slug: str


org_context: ContextVar[OrgContext | None] = ContextVar("org_context", default=None)


def get_org_context() -> OrgContext:
    ctx = org_context.get()
    if ctx is None:
        raise RuntimeError("Org context not set - ensure request passed through TenancyMiddleware")
    return ctx
