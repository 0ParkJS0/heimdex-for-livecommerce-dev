"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orgs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orgs")),
        sa.UniqueConstraint("slug", name=op.f("uq_orgs_slug")),
    )
    op.create_index(op.f("ix_orgs_slug"), "orgs", ["slug"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_users_org_id_orgs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_org_id"), "users", ["org_id"], unique=False)

    op.create_table(
        "libraries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_libraries_org_id_orgs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name=op.f("fk_libraries_created_by_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_libraries")),
    )
    op.create_index(op.f("ix_libraries_org_id"), "libraries", ["org_id"], unique=False)

    op.create_table(
        "library_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("library_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("segmentation_version", sa.String(50), nullable=False),
        sa.Column("embedding_version", sa.String(50), nullable=False),
        sa.Column("asr_version", sa.String(50), nullable=False),
        sa.Column("face_version", sa.String(50), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_library_profiles_org_id_orgs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], name=op.f("fk_library_profiles_library_id_libraries"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_library_profiles")),
    )
    op.create_index(op.f("ix_library_profiles_org_id"), "library_profiles", ["org_id"], unique=False)
    op.create_index(op.f("ix_library_profiles_library_id"), "library_profiles", ["library_id"], unique=False)

    op.create_table(
        "drive_nickname_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_fingerprint_hash", sa.String(64), nullable=False),
        sa.Column("nickname", sa.String(100), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_drive_nickname_registry_org_id_orgs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drive_nickname_registry")),
    )
    op.create_index(op.f("ix_drive_nickname_registry_org_id"), "drive_nickname_registry", ["org_id"], unique=False)

    op.create_table(
        "people_cluster_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_cluster_id", sa.String(64), nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_people_cluster_labels_org_id_orgs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_people_cluster_labels")),
    )
    op.create_index(op.f("ix_people_cluster_labels_org_id"), "people_cluster_labels", ["org_id"], unique=False)
    op.create_index(op.f("ix_people_cluster_labels_person_cluster_id"), "people_cluster_labels", ["person_cluster_id"], unique=False)


def downgrade() -> None:
    op.drop_table("people_cluster_labels")
    op.drop_table("drive_nickname_registry")
    op.drop_table("library_profiles")
    op.drop_table("libraries")
    op.drop_table("users")
    op.drop_table("orgs")
