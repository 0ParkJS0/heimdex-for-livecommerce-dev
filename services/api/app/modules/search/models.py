from __future__ import annotations

from datetime import datetime
from typing import Any, final
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


@final
class SearchEvent(Base):
    # Uses (BIGSERIAL, created_at) composite PK instead of UUIDMixin for partition compatibility.
    # No TimestampMixin — events are immutable (no updated_at).

    __tablename__ = "search_events"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_mode: Mapped[str] = mapped_column(Text, nullable=False)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # Tell SQLAlchemy this is a partitioned table — don't try to create it
        # via metadata.create_all.  Alembic migration handles DDL.
        {"implicit_returning": False},
    )


@final
class SearchInteraction(Base):
    # Search-result interaction log (impression / click / play_*). Mirrors
    # SearchEvent's (BIGSERIAL, created_at) composite PK for monthly RANGE
    # partition compatibility; events are immutable (no updated_at).
    #
    # ``search_event_id`` links back to the originating search_events row but is
    # a plain BIGINT — NOT a foreign key. The parent is a partitioned table with
    # a composite (id, created_at) PK, so a single-column FK is impossible; the
    # join is done in BigQuery for analytics.

    __tablename__ = "search_interactions"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    search_event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # impression | click | play_start | play_complete (plain TEXT, mirrors
    # search_events.search_mode — new types need no migration).
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    result_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scene_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Search surface the result came from: "video" | "image" (matches
    # SceneResult.content_type / SearchRequest.content_types). Lets CTR be
    # split by 동영상 검색 vs 이미지 검색 without parsing metadata.
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    dwell_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # Partitioned table — DDL is owned by the Alembic migration, not
        # metadata.create_all.
        {"implicit_returning": False},
    )
