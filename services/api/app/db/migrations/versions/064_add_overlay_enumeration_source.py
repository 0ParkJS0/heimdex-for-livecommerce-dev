"""Add 'overlay' to the enumeration_source CHECK constraint.

The overlay-enumeration-worker migration adds a SECOND enumeration pass
(``services/product-enumerate-worker`` mode ``vision+overlay`` /
``overlay``) that reads on-screen info-overlay graphics and writes
catalog rows with ``enumeration_source='overlay'``. The CHECK constraint
created in migration 055 locks the set to
``{vision, stt, stt_xref, manifest, hybrid}`` — an overlay-source insert
would 400 at the DB. Widen the set to include ``overlay``.

Postgres cannot ALTER a CHECK constraint in place, so the upgrade DROPs
the existing constraint and re-ADDs it with the widened value set; the
downgrade reverses it (DROP wide, ADD narrow). Both are guarded by a
``pg_constraint`` lookup so re-runs are idempotent.

Pattern: identical to migration 055's CHECK handling. CHECK rather than
a Postgres ENUM type sidesteps the
ENUM-add-value-needs-transaction-per-migration footgun
(``feedback_alembic_enum_add_value_pattern.md``).

Revision ID: 064_add_overlay_enumeration_source
Revises: 063_add_tangibility_to_video_summaries
Create Date: 2026-05-25

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "064_add_overlay_enumeration_source"
down_revision: str | None = "063_add_tangibility_to_video_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CHECK_CONSTRAINT_NAME = "ck_product_catalog_enumeration_source"
# Migration 055's set + 'overlay'.
_WIDE_SET = "('vision', 'stt', 'stt_xref', 'manifest', 'hybrid', 'overlay')"
_NARROW_SET = "('vision', 'stt', 'stt_xref', 'manifest', 'hybrid')"


def _recreate_constraint(allowed_set: str) -> None:
    """DROP + ADD the CHECK constraint with the given value set.

    Guarded so a re-run (or a fresh DB where the constraint may differ)
    converges to the requested set."""
    op.execute(f"""
        ALTER TABLE product_catalog_entries
            DROP CONSTRAINT IF EXISTS {_CHECK_CONSTRAINT_NAME}
    """)
    op.execute(f"""
        ALTER TABLE product_catalog_entries
            ADD CONSTRAINT {_CHECK_CONSTRAINT_NAME}
            CHECK (enumeration_source IN {allowed_set})
    """)


def upgrade() -> None:
    _recreate_constraint(_WIDE_SET)


def downgrade() -> None:
    # Reverting will fail if any 'overlay' rows exist (the narrow CHECK
    # rejects them). The downgrade is best-effort for dev; production
    # should never run this once overlay entries have been inserted.
    _recreate_constraint(_NARROW_SET)
