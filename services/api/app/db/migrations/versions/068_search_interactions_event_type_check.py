"""Add CHECK constraint on search_interactions.event_type

Revision ID: 068_search_interactions_event_type_check
Revises: 067_create_search_interactions
Create Date: 2026-06-09

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "068_search_interactions_event_type_check"
down_revision: str | None = "067_create_search_interactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The closed set the API writes (mirrors InteractionItem.event_type Literal).
# play_start/play_complete are reserved for Phase 2 so the constraint needs no
# future migration when those start being logged.
_ALLOWED_EVENT_TYPES = ("impression", "click", "play_start", "play_complete")
_CONSTRAINT_NAME = "ck_search_interactions_event_type"


def upgrade() -> None:
    # CHECK on the partitioned parent propagates to all partitions. This is the
    # DB-level last line of defense: the Pydantic Literal only guards the API,
    # not direct SQL / scripts / migrations.
    values = ", ".join(f"'{v}'" for v in _ALLOWED_EVENT_TYPES)
    op.execute(
        f"ALTER TABLE search_interactions "
        f"ADD CONSTRAINT {_CONSTRAINT_NAME} "
        f"CHECK (event_type IN ({values}))"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE search_interactions "
        f"DROP CONSTRAINT IF EXISTS {_CONSTRAINT_NAME}"
    )
