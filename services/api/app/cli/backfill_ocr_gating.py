"""Re-gate existing OCR text in OpenSearch to match the contracts gating rules.

When the pre-gating bug was live, OCR text was stored unprocessed:
  - no gate_ocr_text (G2 short / G3 noise / G4 over-cap text indexed)
  - ocr_char_count = len(norm), not len(raw_gated)

This CLI scrolls every scene whose ``ocr_text_raw`` is non-empty, replays
``process_ocr_text()`` from ``app.modules.ingest.service``, and bulk-updates
the doc when the result differs. Idempotent — a second run is a no-op for
already-clean rows.

Usage:
    python -m app.cli.backfill_ocr_gating --dry-run
    python -m app.cli.backfill_ocr_gating --limit 100
    python -m app.cli.backfill_ocr_gating --org devorg
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-gate OCR text in OpenSearch per the contracts contract"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max scenes to process (0 = unlimited)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Scenes per scroll batch (default 200)",
    )
    parser.add_argument(
        "--org",
        type=str,
        default=None,
        help="Restrict to one org slug (default: all orgs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count changes, do not write to OpenSearch",
    )
    return parser.parse_args()


async def _resolve_org_id(org_slug: str) -> str:
    """Look up the UUID for an org slug. Lives inside an async fn so we don't
    keep a DB session open across the whole scroll loop."""
    from sqlalchemy import select

    from app.db.session import async_session_factory
    from app.modules.orgs.models import Org

    async with async_session_factory() as session:
        row = (
            await session.execute(select(Org).where(Org.slug == org_slug))
        ).scalar_one_or_none()
        if row is None:
            raise SystemExit(f"org slug not found: {org_slug}")
        return str(row.id)


async def _backfill(
    limit: int,
    batch_size: int,
    dry_run: bool,
    org_id: str | None,
) -> None:
    from app.modules.ingest.service import process_ocr_text
    from app.modules.search.scene_client import SceneSearchClient

    client = SceneSearchClient()

    query: dict[str, Any] = {
        "bool": {
            "must": [{"exists": {"field": "ocr_text_raw"}}],
            # OpenSearch keyword exists() returns true for empty strings too;
            # filter those out so dry-run counts stay honest.
            "must_not": [{"term": {"ocr_text_raw.keyword": ""}}],
        }
    }
    if org_id is not None:
        query["bool"]["must"].append({"term": {"org_id": org_id}})

    body: dict[str, Any] = {
        "query": query,
        "size": batch_size,
        "_source": ["org_id", "video_id", "scene_id", "ocr_text_raw", "ocr_char_count"],
        "sort": [{"_doc": "asc"}],
    }

    scanned = 0
    changed = 0
    cleared = 0  # gated to empty
    unchanged = 0

    while True:
        if limit > 0 and scanned >= limit:
            break

        response = await client.client.search(index=client.alias_name, body=body)
        hits = response["hits"]["hits"]
        if not hits:
            break

        updates: list[tuple[str, dict[str, Any]]] = []
        for hit in hits:
            if limit > 0 and scanned >= limit:
                break
            scanned += 1

            src = hit["_source"]
            doc_id = hit["_id"]
            current_raw = src.get("ocr_text_raw") or ""
            current_count = src.get("ocr_char_count")

            new_raw, new_norm, new_count = process_ocr_text(current_raw)

            # Idempotency check: if the gated text and the char_count both
            # already match what process_ocr_text would produce, this row
            # was either ingested post-fix or already backfilled. Skip.
            if new_raw == current_raw and new_count == current_count:
                unchanged += 1
                continue

            if not new_raw:
                cleared += 1
            else:
                changed += 1

            updates.append(
                (
                    doc_id,
                    {
                        "ocr_text_raw": new_raw,
                        "ocr_text_norm": new_norm,
                        "ocr_char_count": new_count,
                    },
                )
            )

        if updates and not dry_run:
            await client.bulk_partial_update_scenes(updates)

        logger.info(
            "progress scanned=%d changed=%d cleared=%d unchanged=%d",
            scanned,
            changed,
            cleared,
            unchanged,
        )

        body["search_after"] = hits[-1]["sort"]

    logger.info(
        "done scanned=%d changed=%d cleared=%d unchanged=%d dry_run=%s",
        scanned,
        changed,
        cleared,
        unchanged,
        dry_run,
    )
    await client.close()


def main() -> None:
    args = _parse_args()
    org_id: str | None = None
    if args.org is not None:
        org_id = asyncio.run(_resolve_org_id(args.org))
    asyncio.run(
        _backfill(
            limit=args.limit,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            org_id=org_id,
        )
    )


if __name__ == "__main__":
    main()
