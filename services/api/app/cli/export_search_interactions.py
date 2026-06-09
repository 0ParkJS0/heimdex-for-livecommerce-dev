"""Nightly export: search_interactions partition → Parquet → S3 → BigQuery.

Usage:
    python -m app.cli.export_search_interactions                   # exports yesterday
    python -m app.cli.export_search_interactions --date 2026-06-08 # specific date
    python -m app.cli.export_search_interactions --dry-run         # print plan only

Unlike search_events/worker_events (single fetch capped at 100k rows), this
exporter is CHUNKED via keyset pagination: search_interactions is high-volume
(impressions ≈ result_count per search), so a single day can exceed 100k rows.
Each chunk is written as its own Parquet part (``{date}.partNNN.parquet``) and
appended to BigQuery, keeping memory bounded and avoiding silent truncation.

Requires pyarrow (optional dependency — only needed for export, not at runtime).
BigQuery load requires google-cloud-bigquery (optional, gated by ANALYTICS_BQ_ENABLED).
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Rows per keyset chunk. Each chunk is one Parquet part + one BQ append.
_CHUNK_SIZE = 50_000


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export search interactions to S3 as Parquet")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to export (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be exported without writing to S3.",
    )
    return parser.parse_args()


def _export_date(target: date) -> tuple[datetime, datetime]:
    start = datetime(target.year, target.month, target.day, tzinfo=UTC)
    end = start + timedelta(days=1)
    return start, end


def _rows_to_parquet(rows: list[dict[str, Any]]) -> bytes:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        logger.error("pyarrow is required for Parquet export. Install with: pip install pyarrow")
        sys.exit(1)

    if not rows:
        return b""

    schema = pa.schema(
        [
            ("id", pa.int64()),
            ("org_id", pa.string()),
            ("user_id", pa.string()),
            ("search_event_id", pa.int64()),
            ("event_type", pa.string()),
            ("result_position", pa.int32()),
            ("scene_id", pa.string()),
            ("video_id", pa.string()),
            ("content_type", pa.string()),
            ("dwell_ms", pa.int32()),
            ("metadata", pa.string()),
            ("created_at", pa.timestamp("us", tz="UTC")),
        ]
    )

    def _opt_str(v: Any) -> str | None:
        return str(v) if v is not None else None

    arrays = [
        pa.array([r["id"] for r in rows], type=pa.int64()),
        pa.array([_opt_str(r.get("org_id")) for r in rows], type=pa.string()),
        pa.array([_opt_str(r.get("user_id")) for r in rows], type=pa.string()),
        pa.array([r.get("search_event_id") for r in rows], type=pa.int64()),
        pa.array([r["event_type"] for r in rows], type=pa.string()),
        pa.array([r.get("result_position") for r in rows], type=pa.int32()),
        pa.array([r.get("scene_id") for r in rows], type=pa.string()),
        pa.array([r.get("video_id") for r in rows], type=pa.string()),
        pa.array([r.get("content_type") for r in rows], type=pa.string()),
        pa.array([r.get("dwell_ms") for r in rows], type=pa.int32()),
        pa.array([json.dumps(r.get("metadata", {})) for r in rows], type=pa.string()),
        pa.array([r["created_at"] for r in rows], type=pa.timestamp("us", tz="UTC")),
    ]

    table = pa.table(arrays, schema=schema)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


def _upload_to_s3(data: bytes, bucket: str, key: str, region: str) -> None:
    import boto3
    from botocore.config import Config as BotoConfig

    client = boto3.client(
        "s3",
        region_name=region,
        config=BotoConfig(retries={"max_attempts": 3, "mode": "adaptive"}),
    )
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/octet-stream")
    logger.info("uploaded_to_s3", extra={"bucket": bucket, "key": key, "size_bytes": len(data)})


def _upload_to_bq(data: bytes, project: str, dataset: str) -> None:
    """Load Parquet bytes into the BQ native table via APPEND."""
    import boto3
    from google.api_core.retry import Retry
    from google.cloud import bigquery

    # google-auth's AWS provider cannot read IMDSv2 metadata inside Docker
    # containers, while boto3 handles it correctly.  Bridge boto3 credentials
    # to env vars so google-auth skips the metadata service entirely.
    session = boto3.Session()
    creds = session.get_credentials()
    if creds:
        frozen = creds.get_frozen_credentials()
        os.environ["AWS_ACCESS_KEY_ID"] = frozen.access_key
        os.environ["AWS_SECRET_ACCESS_KEY"] = frozen.secret_key
        if frozen.token:
            os.environ["AWS_SESSION_TOKEN"] = frozen.token

    client = bigquery.Client(project=project)
    table_id = f"{project}.{dataset}.search_interactions"

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
    )

    bq_retry = Retry(initial=1.0, maximum=4.0, multiplier=2.0, deadline=30.0)

    @bq_retry
    def _do_load() -> bigquery.LoadJob:
        job = client.load_table_from_file(io.BytesIO(data), table_id, job_config=job_config)
        job.result(timeout=120)
        return job

    load_job = _do_load()
    logger.info(
        "bq_load_complete",
        extra={"table_id": table_id, "rows": load_job.output_rows},
    )


def main() -> None:
    args = _parse_args()

    target = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)

    date_from, date_to = _export_date(target)
    logger.info(f"Exporting search interactions for {target.isoformat()}")

    from app.config import get_settings

    settings = get_settings()

    if not settings.analytics_export_enabled:
        logger.info("ANALYTICS_EXPORT_ENABLED=false — skipping export.")
        return

    bucket = settings.analytics_s3_bucket or settings.drive_s3_bucket
    prefix = settings.analytics_s3_prefix

    def _s3_key(part: int) -> str:
        return (
            f"{prefix}/search_interactions/"
            f"year={target.year}/month={target.month:02d}/day={target.day:02d}/"
            f"{target.isoformat()}.part{part:03d}.parquet"
        )

    if args.dry_run:
        logger.info(f"[DRY RUN] Would export (chunked) to s3://{bucket}/{_s3_key(0)} ...")
        return

    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.models  # noqa: F401 — register all models for mapper resolution
    from app.db.base import get_async_engine
    from app.modules.search.search_interaction_repository import (
        SearchInteractionRepository,
    )

    bq_enabled = settings.analytics_bq_enabled and bool(settings.analytics_bq_project)
    if settings.analytics_bq_enabled and not settings.analytics_bq_project:
        logger.error("ANALYTICS_BQ_PROJECT is required when ANALYTICS_BQ_ENABLED=true")

    async def _run() -> int:
        nonlocal bq_enabled
        engine = get_async_engine()
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        after: tuple[datetime, int] | None = None
        part = 0
        total = 0
        async with factory() as session:
            repo = SearchInteractionRepository(session)
            while True:
                interactions = await repo.list_for_export(
                    date_from=date_from,
                    date_to=date_to,
                    after=after,
                    limit=_CHUNK_SIZE,
                )
                if not interactions:
                    break
                rows = [
                    {
                        "id": e.id,
                        "org_id": e.org_id,
                        "user_id": e.user_id,
                        "search_event_id": e.search_event_id,
                        "event_type": e.event_type,
                        "result_position": e.result_position,
                        "scene_id": e.scene_id,
                        "video_id": e.video_id,
                        "content_type": e.content_type,
                        "dwell_ms": e.dwell_ms,
                        "metadata": e.metadata_,
                        "created_at": e.created_at,
                    }
                    for e in interactions
                ]
                parquet_data = _rows_to_parquet(rows)
                _upload_to_s3(parquet_data, bucket, _s3_key(part), settings.s3_region)
                if bq_enabled:
                    try:
                        _upload_to_bq(
                            parquet_data,
                            settings.analytics_bq_project,
                            settings.analytics_bq_dataset,
                        )
                    except Exception as exc:
                        # Predictable failure when GCP Workload Identity Federation
                        # isn't wired (see project_prod_bq_federation_unwired.md).
                        # Match by class name to avoid a hard dependency on
                        # google.auth.exceptions at import time.
                        if type(exc).__name__ == "DefaultCredentialsError":
                            logger.warning(
                                "bq_load_skipped_no_credentials",
                                extra={"project": settings.analytics_bq_project},
                            )
                            # Don't retry BQ for every remaining chunk once we know
                            # credentials are missing — S3 upload already succeeded.
                            bq_enabled = False
                        else:
                            logger.exception(
                                "BQ load failed for part %s — S3 upload OK, continuing",
                                part,
                            )
                total += len(interactions)
                last = interactions[-1]
                after = (last.created_at, last.id)
                part += 1
                if len(interactions) < _CHUNK_SIZE:
                    break
        return total

    total = asyncio.run(_run())
    logger.info(f"Export complete: {total} interactions for {target.isoformat()}")


if __name__ == "__main__":
    main()
