from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.modules.orgs.models import Org
    from app.modules.profiles.models import LibraryProfile
    from app.modules.users.models import User


class Library(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "libraries"
    
    org_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    org: Mapped["Org"] = relationship("Org", back_populates="libraries")
    created_by: Mapped["User"] = relationship("User", lazy="selectin")
    profiles: Mapped[list["LibraryProfile"]] = relationship(
        "LibraryProfile", back_populates="library", lazy="selectin"
    )
