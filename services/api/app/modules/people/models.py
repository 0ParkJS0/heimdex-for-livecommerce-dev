from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class DriveNicknameRegistry(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "drive_nickname_registry"
    
    org_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nickname: Mapped[str] = mapped_column(String(100), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    
    __table_args__ = (
        {"comment": "Registry of removable drive nicknames for display in UI"},
    )


class PeopleClusterLabel(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "people_cluster_labels"
    
    org_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_cluster_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    __table_args__ = (
        {"comment": "Labels for face clusters within an org"},
    )
