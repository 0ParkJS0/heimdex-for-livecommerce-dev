"""Create search_interactions partitioned table for search-result interactions

Revision ID: 067_create_search_interactions
Revises: 066_widen_scan_order_duration_preset_check
Create Date: 2026-06-08

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "067_create_search_interactions"
down_revision: str | None = "066_widen_scan_order_duration_preset_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Monthly RANGE partitions are created at runtime by
    # SearchInteractionRepository.ensure_partitions (mirrors search_events).
    # search_event_id is a plain BIGINT — NOT a FK: the parent search_events is
    # partitioned with a composite (id, created_at) PK, so a single-column FK is
    # impossible; the join happens in BigQuery.
    op.execute(
        """
        CREATE TABLE search_interactions (
            id              BIGSERIAL    NOT NULL,
            org_id          UUID         NOT NULL,
            user_id         UUID         NOT NULL,
            search_event_id BIGINT,
            event_type      TEXT         NOT NULL,
            result_position INTEGER,
            scene_id        TEXT,
            video_id        TEXT,
            content_type    TEXT,
            dwell_ms        INTEGER,
            metadata        JSONB        NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
        """
    )

    # B-tree on (org_id, created_at DESC) — org-scoped analytics scans.
    op.execute(
        "CREATE INDEX ix_search_interactions_org_time "
        "ON search_interactions (org_id, created_at DESC)"
    )
    # Join back to the originating search event.
    op.execute("CREATE INDEX ix_search_interactions_event ON search_interactions (search_event_id)")
    # Per-scene CTR / funnel by event_type.
    op.execute(
        "CREATE INDEX ix_search_interactions_scene_type "
        "ON search_interactions (scene_id, event_type)"
    )
    # BRIN on created_at — compact index for time-range scans on partitioned data.
    op.execute(
        "CREATE INDEX ix_search_interactions_time_brin "
        "ON search_interactions USING BRIN (created_at)"
    )


def downgrade() -> None:
    # Dropping the parent cascades to all partitions.
    op.execute("DROP TABLE IF EXISTS search_interactions CASCADE")
