"""Add full-STT shared-planner columns to product_scan_jobs.

The shared planner (one LLM call → N distinct shorts) persists each child's
plan and gates child pickup on a parent marker. Two additive columns + one
partial index:

* ``full_stt_plan JSONB NULL`` — the persisted ``FullSttClipPlan`` for a
  ``mode='render_child'`` row, written by the planner and read by the render
  child (no per-child LLM call). NULL on every non-shared-plan row.

* ``full_stt_shared_plan_pending BOOLEAN NOT NULL DEFAULT false`` — parent
  (``mode='scan_order'``) gate marker. Set true at fan-out when the shared
  planner flag is on; the planner clears it once N plans are persisted, which
  unlocks the children for the runner's child poll. Default false → every
  existing row + every non-shared-plan parent is immediately claimable, so
  SAM2 / storyboard / flag-off paths are unaffected.

* ``ix_psj_planner_queue`` — partial index over the planner poll's hot
  predicate so it doesn't sequential-scan product_scan_jobs.

Strictly additive. The boolean has a constant server default, so Postgres
adds it without a full-table rewrite. No backfill, no row touches. Avoids the
``product_scan_stage`` ENUM entirely (deliberate — no cross-repo
heimdex-media-contracts release; see
``.claude/plans/full-stt-shared-planner-2026-05-20.md`` §4.2). Runs in the
migration's own transaction (``transaction_per_migration=True`` in env.py).

Revision ID: 060_add_full_stt_shared_plan
Revises: 059_add_render_summary
Create Date: 2026-05-20
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "060_add_full_stt_shared_plan"
down_revision: str | None = "059_add_render_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_scan_jobs",
        sa.Column("full_stt_plan", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "product_scan_jobs",
        sa.Column(
            "full_stt_shared_plan_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_psj_planner_queue
            ON product_scan_jobs (created_at)
            WHERE mode = 'scan_order'
              AND full_stt_shared_plan_pending = true
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_psj_planner_queue")
    op.drop_column("product_scan_jobs", "full_stt_shared_plan_pending")
    op.drop_column("product_scan_jobs", "full_stt_plan")
