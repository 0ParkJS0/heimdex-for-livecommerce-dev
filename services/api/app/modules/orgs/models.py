from typing import Any

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

User = Any
Library = Any


class Org(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "orgs"

    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_api_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    users: Mapped[list[User]] = relationship("User", back_populates="org", lazy="selectin")
    libraries: Mapped[list[Library]] = relationship("Library", back_populates="org", lazy="selectin")
