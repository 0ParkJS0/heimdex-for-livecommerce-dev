from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.modules.libraries.models import Library


class ProfileStatus(str, Enum):
    BUILDING = "building"
    READY = "ready"
    ACTIVE = "active"
    FAILED = "failed"


class LibraryProfile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "library_profiles"
    
    org_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    library_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("libraries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[ProfileStatus] = mapped_column(
        String(20), nullable=False, default=ProfileStatus.BUILDING
    )
    segmentation_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    embedding_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    asr_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    face_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    library: Mapped["Library"] = relationship("Library", back_populates="profiles")
