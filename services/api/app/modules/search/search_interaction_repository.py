from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger

from .models import SearchInteraction

logger = get_logger(__name__)


class SearchInteractionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        event_type: str,
        search_event_id: int | None = None,
        result_position: int | None = None,
        scene_id: str | None = None,
        video_id: str | None = None,
        content_type: str | None = None,
        dwell_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SearchInteraction:
        interaction = SearchInteraction(
            org_id=org_id,
            user_id=user_id,
            event_type=event_type,
            search_event_id=search_event_id,
            result_position=result_position,
            scene_id=scene_id,
            video_id=video_id,
            content_type=content_type,
            dwell_ms=dwell_ms,
            metadata_=metadata or {},
        )
        self.session.add(interaction)
        await self.session.flush()
        return interaction

    async def create_many(self, rows: list[dict[str, Any]]) -> int:
        """Bulk-insert interactions (used by batch impression logging).

        Each row carries the same keys as ``create`` parameters. Returns the
        number of rows inserted.
        """
        objs = [
            SearchInteraction(
                org_id=row["org_id"],
                user_id=row["user_id"],
                event_type=row["event_type"],
                search_event_id=row.get("search_event_id"),
                result_position=row.get("result_position"),
                scene_id=row.get("scene_id"),
                video_id=row.get("video_id"),
                content_type=row.get("content_type"),
                dwell_ms=row.get("dwell_ms"),
                metadata_=row.get("metadata") or {},
            )
            for row in rows
        ]
        self.session.add_all(objs)
        await self.session.flush()
        return len(objs)

    async def list_for_export(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        after: tuple[datetime, int] | None,
        limit: int,
    ) -> list[SearchInteraction]:
        """Keyset-paginated rows for chunked BQ export.

        Returns up to ``limit`` rows in (created_at, id) order within the
        ``[date_from, date_to)`` window, strictly after the ``after`` cursor.
        Keyset (not OFFSET) keeps each chunk O(limit) so high-volume days
        export without truncation or slow deep paging.
        """
        stmt = select(SearchInteraction).where(
            SearchInteraction.created_at >= date_from,
            SearchInteraction.created_at < date_to,
        )
        if after is not None:
            stmt = stmt.where(
                tuple_(SearchInteraction.created_at, SearchInteraction.id)
                > tuple_(after[0], after[1])
            )
        stmt = stmt.order_by(SearchInteraction.created_at.asc(), SearchInteraction.id.asc()).limit(
            limit
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def ensure_partitions(self, months_ahead: int = 2) -> list[str]:
        """Idempotent partition creation for current month + N months ahead.

        Must be called on every startup — partitioned tables reject inserts
        into date ranges without a matching partition.
        """
        now = datetime.now(UTC)
        created: list[str] = []

        for offset in range(months_ahead + 1):
            month = now.month + offset
            year = now.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1

            next_month = month + 1
            next_year = year + (next_month - 1) // 12
            next_month = ((next_month - 1) % 12) + 1

            partition_name = f"search_interactions_{year}_{month:02d}"
            from_date = f"{year}-{month:02d}-01"
            to_date = f"{next_year}-{next_month:02d}-01"

            await self.session.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {partition_name} "
                    f"PARTITION OF search_interactions "
                    f"FOR VALUES FROM ('{from_date}') TO ('{to_date}')"
                )
            )
            created.append(partition_name)

        await self.session.flush()
        logger.info(
            "search_interaction_partitions_ensured",
            partitions=created,
            months_ahead=months_ahead,
        )
        return created
