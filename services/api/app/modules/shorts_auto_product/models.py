"""SQLAlchemy models for shorts-auto product mode v2.

Mirrors migration 051_create_product_catalog. Field-for-field
correspondence; do not drift without a migration update.

Three core tables + a daily-cost ledger:

* :class:`ProductCatalogEntry` — one distinct product detected in a
  video (lazy, populated on first user click). Per-video v1.
* :class:`ProductAppearance` — one qualifying appearance window for a
  ``(catalog_entry, scene)``. Frame-level bbox track lives in S3.
* :class:`ProductScanJob` — async job state machine. ``catalog_entry_id``
  ``NULL`` = enumeration job; non-null = tracking + assembly job.
* :class:`ProductScanDailyCost` — per-org-per-day running cost for
  the budget cap. Separate bucket from auto_shorts_llm /
  image_caption / video_summary.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, final
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy import Date as SADate
from sqlalchemy.dialects.postgresql import ARRAY, REAL
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, TimestampMixin, UUIDMixin


# ---------- product_scan_jobs.stage ENUM ----------
#
# Created in raw SQL by migration 051. ``create_type=False`` tells
# SQLAlchemy not to attempt a re-create — the migration owns the type.
# Keep these literals in lockstep with:
#   * migration 051's ``CREATE TYPE product_scan_stage AS ENUM (...)``
#   * heimdex_media_contracts.product.ProductScanStage Literal
#   * heimdex_media_contracts.product.ALLOWED_SCAN_STAGES frozenset
SCAN_STAGE_QUEUED = "queued"
SCAN_STAGE_ENUMERATING = "enumerating"
SCAN_STAGE_ENUMERATION_DONE = "enumeration_done"
SCAN_STAGE_TRACKING = "tracking"
SCAN_STAGE_ASSEMBLING = "assembling"
SCAN_STAGE_RENDERING = "rendering"
SCAN_STAGE_DONE = "done"
SCAN_STAGE_FAILED = "failed"
SCAN_STAGE_CANCELLED = "cancelled"

ALL_SCAN_STAGES: tuple[str, ...] = (
    SCAN_STAGE_QUEUED,
    SCAN_STAGE_ENUMERATING,
    SCAN_STAGE_ENUMERATION_DONE,
    SCAN_STAGE_TRACKING,
    SCAN_STAGE_ASSEMBLING,
    SCAN_STAGE_RENDERING,
    SCAN_STAGE_DONE,
    SCAN_STAGE_FAILED,
    SCAN_STAGE_CANCELLED,
)

# Stages where the job is still in-flight — drives the per-org
# concurrency cap query (``ix_product_scan_jobs_active``).
ACTIVE_SCAN_STAGES: frozenset[str] = frozenset({
    SCAN_STAGE_QUEUED,
    SCAN_STAGE_ENUMERATING,
    SCAN_STAGE_TRACKING,
    SCAN_STAGE_ASSEMBLING,
    SCAN_STAGE_RENDERING,
})

TERMINAL_SCAN_STAGES: frozenset[str] = frozenset({
    SCAN_STAGE_DONE,
    SCAN_STAGE_FAILED,
    SCAN_STAGE_CANCELLED,
})

# SQLAlchemy enum type bound to the existing Postgres ENUM. All ORM
# reads / writes go through this so type-safety is preserved.
PRODUCT_SCAN_STAGE_ENUM = SAEnum(
    *ALL_SCAN_STAGES,
    name="product_scan_stage",
    create_type=False,
    native_enum=True,
    validate_strings=True,
)


# ---------- ProductCatalogEntry ----------

@final
class ProductCatalogEntry(Base, UUIDMixin, TimestampMixin):
    """One distinct product detected in a video.

    Populated lazily by ``product-enumerate-worker`` on first user
    click. ``rejected_at`` is a soft delete — rejected rows are kept
    for threshold tuning so we can re-classify without re-running
    enumeration.
    """

    __tablename__ = "product_catalog_entries"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    video_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("drive_files.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Best reference frame — chosen by the reference picker's quality
    # composite, NOT by first appearance. Lets re-id / SAM2 anchor on
    # the highest-quality crop instead of an intro montage flash.
    canonical_crop_s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_video_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    canonical_frame_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_bbox_x: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_bbox_y: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_bbox_w: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_bbox_h: Mapped[int] = mapped_column(Integer, nullable=False)

    llm_label: Mapped[str] = mapped_column(Text, nullable=False)
    user_label: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 768-dim matches google/siglip2-base-patch16-256 deployed in
    # drive-visual-embed-worker. Bumping this dim is a coordinated
    # migration across both workers and OS — never change in isolation.
    siglip2_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(768), nullable=True,
    )

    enumeration_confidence: Mapped[float] = mapped_column(REAL, nullable=False)
    prominence_score: Mapped[float] = mapped_column(REAL, nullable=False)

    enumeration_version: Mapped[str] = mapped_column(Text, nullable=False)
    enumeration_prompt_version: Mapped[str] = mapped_column(Text, nullable=False)

    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__: tuple[Any, ...] = (
        # Active-only index for the gallery view query.
        Index(
            "ix_product_catalog_org_video",
            "org_id", "video_id",
            postgresql_where=(rejected_at.is_(None)),
        ),
        # Cross-video kNN (v2 prep — populated from day one).
        Index(
            "ix_product_catalog_siglip2",
            "siglip2_embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"siglip2_embedding": "vector_cosine_ops"},
        ),
    )


# ---------- ProductAppearance ----------

@final
class ProductAppearance(Base, UUIDMixin):
    """One contiguous appearance window for a catalog entry.

    Note: no ``updated_at`` — appearances are append-only per scan.
    Re-running tracking on the same catalog entry inserts a new batch
    keyed by ``tracker_version``; old rows stay until explicitly purged.
    """

    __tablename__ = "product_appearances"

    catalog_entry_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("product_catalog_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalized for the multi-tenant guard — querying appearances
    # by id alone would otherwise need a join to validate ownership.
    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )

    # OpenSearch ``scene_id`` (no org prefix); join via
    # ``f"{org_id}:{scene_id}"`` per existing convention.
    scene_id: Mapped[str] = mapped_column(Text, nullable=False)
    window_start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    window_end_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    avg_bbox_area_pct: Mapped[float] = mapped_column(REAL, nullable=False)
    avg_confidence: Mapped[float] = mapped_column(REAL, nullable=False)
    has_narration_mention: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    has_ocr_overlap: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    co_appearing_catalog_entry_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)),
        nullable=False,
        server_default="{}",
    )

    # Frame-level bbox track lives in S3, never in Postgres — at 5fps
    # over 60 minutes that's 18k rows per appearance, which is far
    # cheaper to scan as a gzipped blob than as relational rows.
    raw_bbox_track_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    tracker_version: Mapped[str] = mapped_column(Text, nullable=False)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__: tuple[Any, ...] = (
        # Active-only — driven by the `rejected_reason IS NULL` partial
        # index in the migration. Speeds up the common "give me the
        # qualifying appearances for this product" query.
        Index(
            "ix_product_appearances_catalog",
            "catalog_entry_id",
            postgresql_where=(rejected_reason.is_(None)),
        ),
        Index("ix_product_appearances_org", "org_id"),
        # Mirrors the migration's CHECK — kept here so SQLAlchemy
        # autogenerate doesn't try to drop / recreate it on next
        # alembic revision --autogenerate.
        CheckConstraint(
            "window_end_ms > window_start_ms",
            name="ck_product_appearances_window_order",
        ),
    )


# ---------- ProductScanJob ----------

@final
class ProductScanJob(Base, UUIDMixin):
    """Async job state machine for the cold-start UX.

    ``catalog_entry_id IS NULL`` ⇒ enumeration job (output:
    ``catalog_entries``). ``catalog_entry_id`` non-null ⇒ tracking +
    assembly job (output: ``render_job_id``).

    Worker lease pattern matches blur. Stale workers can never
    overwrite a re-claimed job because the ``/internal/products/*``
    callbacks check ``claimed_by`` against the row before mutating.
    """

    __tablename__ = "product_scan_jobs"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    video_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("drive_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Enumeration job vs tracking job.
    catalog_entry_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("product_catalog_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    duration_preset_sec: Mapped[int] = mapped_column(Integer, nullable=False)

    stage: Mapped[str] = mapped_column(
        PRODUCT_SCAN_STAGE_ENUM,
        nullable=False,
        server_default=SCAN_STAGE_QUEUED,
    )
    progress_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    progress_label: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Worker lease (mirrors blur).
    claimed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Output of tracking jobs.
    render_job_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("shorts_render_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Running cost tally — workers add to this on every heartbeat so
    # the cap-check remains O(1) instead of summing job rows.
    cost_usd_estimate: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default="0",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__: tuple[Any, ...] = (
        Index("ix_product_scan_jobs_org_video", "org_id", "video_id"),
        Index(
            "ix_product_scan_jobs_user_recent",
            "requested_by_user_id", "created_at",
        ),
        # Active-only — drives the per-org concurrency cap. Mirrors the
        # ENUM list in ACTIVE_SCAN_STAGES; keep both in sync.
        Index(
            "ix_product_scan_jobs_active",
            "org_id", "stage",
            postgresql_where=(stage.in_(list(ACTIVE_SCAN_STAGES))),
        ),
        # Idempotency lookup for the 60s scan-debounce window.
        Index(
            "ix_product_scan_jobs_idempotency",
            "video_id", "requested_by_user_id", "catalog_entry_id", "created_at",
        ),
    )


# ---------- ProductScanDailyCost ----------

@final
class ProductScanDailyCost(Base):
    """Per-org-per-day running cost for the v2 budget cap.

    Composite PK ``(org_id, day)`` — at most one row per org per UTC
    day. Workers and the API both update via ``ON CONFLICT … DO
    UPDATE`` so concurrent heartbeats don't lose increments.
    """

    __tablename__ = "product_scan_daily_costs"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    day: Mapped[date] = mapped_column(SADate, primary_key=True, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default="0",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


__all__ = [
    "ACTIVE_SCAN_STAGES",
    "ALL_SCAN_STAGES",
    "PRODUCT_SCAN_STAGE_ENUM",
    "ProductAppearance",
    "ProductCatalogEntry",
    "ProductScanDailyCost",
    "ProductScanJob",
    "SCAN_STAGE_ASSEMBLING",
    "SCAN_STAGE_CANCELLED",
    "SCAN_STAGE_DONE",
    "SCAN_STAGE_ENUMERATING",
    "SCAN_STAGE_ENUMERATION_DONE",
    "SCAN_STAGE_FAILED",
    "SCAN_STAGE_QUEUED",
    "SCAN_STAGE_RENDERING",
    "SCAN_STAGE_TRACKING",
    "TERMINAL_SCAN_STAGES",
]
