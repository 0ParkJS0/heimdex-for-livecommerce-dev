"""Ensure partitioned-table partitions exist ahead of time.

The API creates partitions for the current + next 2 months on startup, but a
deployment that runs for more than ~2 months without a restart would hit insert
failures when a new month begins: a Postgres RANGE-partitioned table rejects any
row whose key has no matching partition. This CLI is meant to run on a daily
cron so partition coverage is guaranteed independent of restarts. All DDL is
IF NOT EXISTS, so it is idempotent.

Usage:
    python -m app.cli.ensure_partitions                  # current + 3 months
    python -m app.cli.ensure_partitions --months-ahead 6
"""
from __future__ import annotations

import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# One more than the startup's 2-month horizon, so the cron stays ahead even if
# it skips a day or two.
_DEFAULT_MONTHS_AHEAD = 3


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ensure DB partitions exist ahead of time")
    parser.add_argument(
        "--months-ahead",
        type=int,
        default=_DEFAULT_MONTHS_AHEAD,
        help=f"Months of future partitions to create (default: {_DEFAULT_MONTHS_AHEAD}).",
    )
    return parser.parse_args()


async def _run(months_ahead: int) -> int:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.models  # noqa: F401 - register all models for mapper resolution
    from app.db.base import get_async_engine
    from app.modules.search.search_event_repository import SearchEventRepository
    from app.modules.search.search_interaction_repository import (
        SearchInteractionRepository,
    )
    from app.modules.worker_events.repository import WorkerEventRepository

    engine = get_async_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    repos = (
        ("search_events", SearchEventRepository),
        ("search_interactions", SearchInteractionRepository),
        ("worker_events", WorkerEventRepository),
    )

    failures = 0
    for label, repo_cls in repos:
        # Each table gets its own session/commit so one failure does not roll
        # back the partitions already created for the others.
        try:
            async with factory() as session:
                repo = repo_cls(session)
                created = await repo.ensure_partitions(months_ahead=months_ahead)
                await session.commit()
                logger.info("partitions ensured for %s: %s", label, created)
        except Exception:
            failures += 1
            logger.exception("partition ensure failed for %s", label)

    return failures


def main() -> None:
    args = _parse_args()
    failures = asyncio.run(_run(args.months_ahead))
    if failures:
        raise SystemExit(f"{failures} partition group(s) failed - see logs above")


if __name__ == "__main__":
    main()
