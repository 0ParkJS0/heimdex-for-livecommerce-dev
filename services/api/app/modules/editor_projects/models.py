"""Editor projects — persisted snapshot of the shorts editor state.

One row per (user, video). The frontend autosaves with a small debounce
(spec recommends 1.5s + beforeunload flush); each PUT replaces the
``state_json`` blob, so revisions live entirely on the client side.
"""

from typing import Any, final
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


@final
class EditorProject(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "editor_projects"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # ``video_id`` is a free-form string because legacy uploads still use the
    # ``gd_<hash>`` form rather than a UUID — same convention as scene_baskets.
    video_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="Untitled")
    # Editor state blob — full ``EditorState`` shape serialized to JSON by
    # the client (clips, subtitles, overlays, transforms, bookmarks, etc).
    # JSONB so partial inspection (``state_json -> 'bookmarks'``) is cheap.
    state_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Bump whenever the client-side serializer changes shape. Loaders can
    # detect older rows and run a migration step before hydration.
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__: tuple[object, ...] = (
        # One project per (user, video) — the frontend always upserts via the
        # PUT-by-video-id endpoint instead of POST+id. Org included so the
        # constraint scales across tenants safely.
        UniqueConstraint(
            "org_id", "user_id", "video_id", name="uq_editor_projects_user_video"
        ),
        Index("ix_editor_projects_org_user_video", "org_id", "user_id", "video_id"),
    )
