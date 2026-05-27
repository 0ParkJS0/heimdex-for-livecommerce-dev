"""Add editor_projects table for autosave snapshots.

One row per (org, user, video) — the shorts editor PUTs its full
``EditorState`` blob here every ~1.5s while the operator is editing.
state_json is JSONB so partial inspection (``state_json -> 'bookmarks'``)
stays cheap without rehydrating the whole client snapshot.

Revision ID: 061_add_editor_projects
Revises: 060_add_full_stt_shared_plan
Create Date: 2026-05-22
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "061_add_editor_projects"
down_revision: str | None = "060_add_full_stt_shared_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "editor_projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("video_id", sa.String(64), nullable=False),
        sa.Column(
            "title",
            sa.String(200),
            nullable=False,
            server_default=sa.text("'Untitled'"),
        ),
        sa.Column(
            "state_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "org_id",
            "user_id",
            "video_id",
            name="uq_editor_projects_user_video",
        ),
    )
    op.create_index(
        "ix_editor_projects_org_id", "editor_projects", ["org_id"]
    )
    op.create_index(
        "ix_editor_projects_user_id", "editor_projects", ["user_id"]
    )
    op.create_index(
        "ix_editor_projects_video_id", "editor_projects", ["video_id"]
    )
    op.create_index(
        "ix_editor_projects_org_user_video",
        "editor_projects",
        ["org_id", "user_id", "video_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_editor_projects_org_user_video", "editor_projects")
    op.drop_index("ix_editor_projects_video_id", "editor_projects")
    op.drop_index("ix_editor_projects_user_id", "editor_projects")
    op.drop_index("ix_editor_projects_org_id", "editor_projects")
    op.drop_table("editor_projects")
