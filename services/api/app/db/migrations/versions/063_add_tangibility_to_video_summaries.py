"""add tangibility columns to video_summaries
Revision ID: 063_add_tangibility_to_video_summaries
Revises: 062_subtitle_preset_composition
Create Date: 2026-05-23
"""
from __future__ import annotations
import sqlalchemy as sa
from alembic import op
revision: str = "063_add_tangibility_to_video_summaries"
down_revision: str | None = "062_subtitle_preset_composition"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.add_column(
        "video_summaries",
        sa.Column("tangibility", sa.String(20), nullable=True),
    )
    op.add_column(
        "video_summaries",
        sa.Column("tangibility_source", sa.String(20), nullable=True),
    )
    op.add_column(
        "video_summaries",
        sa.Column("tangibility_p_intangible", sa.Float(), nullable=True),
    )
    op.add_column(
        "video_summaries",
        sa.Column("tangibility_model_version", sa.String(20), nullable=True),
    )
    op.add_column(
        "video_summaries",
        sa.Column("tangibility_mode", sa.String(20), nullable=True),
    )
    op.create_index(
        "ix_video_summaries_tangibility",
        "video_summaries",
        ["org_id", "tangibility"],
    )
def downgrade() -> None:
    op.drop_index("ix_video_summaries_tangibility", table_name="video_summaries")
    op.drop_column("video_summaries", "tangibility_mode")
    op.drop_column("video_summaries", "tangibility_model_version")
    op.drop_column("video_summaries", "tangibility_p_intangible")
    op.drop_column("video_summaries", "tangibility_source")
    op.drop_column("video_summaries", "tangibility")