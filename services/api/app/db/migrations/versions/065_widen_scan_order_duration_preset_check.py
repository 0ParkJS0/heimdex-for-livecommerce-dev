"""Widen product_scan_jobs duration mirror constraint for scan orders.

Revision ID: 065_widen_scan_order_duration_preset_check
Revises: 064_add_overlay_enumeration_source
Create Date: 2026-05-27
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "065_widen_scan_order_duration_preset_check"
down_revision: str | None = "064_add_overlay_enumeration_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CONSTRAINT_NAME = "product_scan_jobs_duration_preset_sec_check"


def upgrade() -> None:
    # Legacy enumerate/track rows still use fixed presets. Wizard scan-order
    # parents and render children mirror length_seconds into this legacy column,
    # so they must accept the wizard's 10..120 second duration range.
    op.execute(f"""
        ALTER TABLE product_scan_jobs
            DROP CONSTRAINT IF EXISTS {_CONSTRAINT_NAME}
    """)
    op.execute(f"""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT {_CONSTRAINT_NAME}
            CHECK (
                (
                    mode IN ('scan_order', 'render_child')
                    AND duration_preset_sec >= 10
                    AND duration_preset_sec <= 120
                )
                OR (
                    mode NOT IN ('scan_order', 'render_child')
                    AND duration_preset_sec IN (30, 60, 90)
                )
            )
    """)


def downgrade() -> None:
    op.execute(f"""
        ALTER TABLE product_scan_jobs
            DROP CONSTRAINT IF EXISTS {_CONSTRAINT_NAME}
    """)
    op.execute(f"""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT {_CONSTRAINT_NAME}
            CHECK (duration_preset_sec IN (30, 60, 90))
    """)
