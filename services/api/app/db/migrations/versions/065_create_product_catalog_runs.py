"""Create product_catalog_runs readiness table.

Revision ID: 065_create_product_catalog_runs
Revises: 064_add_overlay_enumeration_source
Create Date: 2026-05-27

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "065_create_product_catalog_runs"
down_revision: str | None = "064_add_overlay_enumeration_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_catalog_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_mode", sa.Text(), nullable=False),
        sa.Column("overlay_policy", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("vision_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overlay_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stt_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consolidation_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ("
            "'queued', 'enumerating', 'augmenting_stt', "
            "'consolidating', 'ready', 'failed'"
            ")",
            name="ck_product_catalog_runs_status",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["drive_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["scan_job_id"], ["product_scan_jobs.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_catalog_runs_org_video_created",
        "product_catalog_runs",
        ["org_id", "video_id", "created_at"],
    )
    op.create_index(
        "ix_product_catalog_runs_scan_job",
        "product_catalog_runs",
        ["scan_job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_catalog_runs_scan_job",
        table_name="product_catalog_runs",
    )
    op.drop_index(
        "ix_product_catalog_runs_org_video_created",
        table_name="product_catalog_runs",
    )
    op.drop_table("product_catalog_runs")

