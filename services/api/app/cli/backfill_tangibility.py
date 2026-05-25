"""Backfill tangibility for existing video_summaries rows.
Usage:
    python -m app.cli.backfill_tangibility --org devorg --dry-run
    python -m app.cli.backfill_tangibility --org devorg
"""
from __future__ import annotations
import argparse
import asyncio
from uuid import UUID
from sqlalchemy import select
from app.config import get_settings
from app.db.session import async_session_factory
from app.modules.tangibility import classify_tangibility
from app.modules.video_summary.models import VideoSummary
from app.modules.video_summary.repository import VideoSummaryRepository
from app.modules.orgs.models import Org
async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", required=True, help="org slug, e.g., 'devorg'")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    settings = get_settings()
    if not settings.tangibility_gate_enabled:
        print("WARN: tangibility_gate_enabled=False. Backfill will run anyway.")
    async with async_session_factory() as session:
        org = (await session.execute(
            select(Org).where(Org.slug == args.org)
        )).scalar_one_or_none()
        if org is None:
            print(f"org not found: {args.org}")
            return
        stmt = (
            select(VideoSummary)
            .where(VideoSummary.org_id == org.id)
            .where(VideoSummary.tangibility.is_(None))
        )
        if args.limit:
            stmt = stmt.limit(args.limit)
        rows = (await session.execute(stmt)).scalars().all()
        print(f"target rows: {len(rows)}")
        repo = VideoSummaryRepository(session)
        processed = 0
        for row in rows:
            text = row.summary_override or row.summary
            result = await classify_tangibility(text, settings)
            print(
                f"  {row.video_id}: {result['label']} "
                f"({result['source']}, p={result['p_intangible']})"
            )
            if not args.dry_run:
                row.tangibility = result["label"]
                row.tangibility_source = result["source"]
                row.tangibility_p_intangible = result["p_intangible"]
                row.tangibility_model_version = result["model_version"]
                row.tangibility_mode = result["mode"]
            processed += 1
        if not args.dry_run:
            await session.commit()
            print(f"committed: {processed} rows")
        else:
            print(f"dry-run: would update {processed} rows")
if __name__ == "__main__":
    asyncio.run(main())