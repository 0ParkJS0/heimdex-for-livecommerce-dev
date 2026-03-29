"""Backfill google_created_time for drive_files missing it.

Fetches createdTime from Google Drive API for each affected file,
updates the DB, then updates capture_time in OpenSearch scenes.

Usage (run inside drive-worker container on staging):
    docker compose exec drive-worker python /workspace/scripts/backfill-created-time.py

Or from host via SSH:
    ssh -i ~/.ssh/heimdex-staging.pem ec2-user@3.34.75.63 \
        "cd /opt/heimdex/dev-heimdex-for-livecommerce && \
         docker compose exec -T drive-worker python /workspace/scripts/backfill-created-time.py"
"""

import logging
import os
import sys
import time

import psycopg2
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build as build_google_service
from googleapiclient.errors import HttpError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

API_BASE = os.environ.get("INTERNAL_API_URL", "http://api:8000")
API_KEY = os.environ.get("DRIVE_INTERNAL_API_KEY", "")


def get_files_missing_created_time(db_url: str) -> list[dict]:
    """Query drive_files where google_created_time IS NULL."""
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT df.google_file_id, df.video_id, df.file_name,
                       df.org_id::text as org_id,
                       dc.id as connection_id,
                       dc.access_token, dc.refresh_token, dc.drive_id
                FROM drive_files df
                JOIN drive_connections dc ON df.connection_id = dc.id
                WHERE df.google_created_time IS NULL
                  AND df.is_deleted = false
                ORDER BY df.created_at DESC
            """)
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def fetch_created_time_from_drive(
    google_file_id: str,
    credentials: Credentials,
) -> str | None:
    """Fetch createdTime for a single file from Google Drive API."""
    service = build_google_service("drive", "v3", credentials=credentials)
    try:
        file_meta = service.files().get(
            fileId=google_file_id,
            fields="createdTime",
            supportsAllDrives=True,
        ).execute()
        return file_meta.get("createdTime")
    except HttpError as e:
        logger.warning(f"  DRIVE_ERROR {google_file_id}: {e}")
        return None


def update_db(video_id: str, created_time: str, db_url: str) -> bool:
    """Update google_created_time in drive_files."""
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE drive_files SET google_created_time = %s WHERE video_id = %s AND google_created_time IS NULL",
                (created_time, video_id),
            )
            updated = cur.rowcount
            conn.commit()
            return updated > 0
    finally:
        conn.close()


def update_opensearch(video_id: str, capture_time: str, org_id: str) -> bool:
    """Update capture_time in OpenSearch scenes via internal API."""
    url = f"{API_BASE}/internal/drive/sync/backfill-capture-time"
    headers = {
        "Content-Type": "application/json",
        "X-Heimdex-Org-Id": org_id,
    }
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    try:
        resp = requests.post(
            url,
            json={"video_id": video_id, "capture_time": capture_time},
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 404:
            logger.warning(f"  OS_SKIP {video_id} — endpoint not found")
            return False
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"  OS_OK {video_id} — {data.get('updated', 0)} scenes updated")
        return True
    except Exception as e:
        logger.warning(f"  OS_ERROR {video_id}: {e}")
        return False


def main():
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)

    logger.info("Fetching files missing google_created_time...")
    files = get_files_missing_created_time(db_url)

    if not files:
        logger.info("No files missing google_created_time — nothing to do")
        return

    logger.info(f"Found {len(files)} files to backfill")

    # Group by connection for credential reuse
    by_connection: dict[str, list[dict]] = {}
    for f in files:
        conn_id = str(f["connection_id"])
        by_connection.setdefault(conn_id, []).append(f)

    db_updated = 0
    os_updated = 0
    failed = 0

    for conn_id, conn_files in by_connection.items():
        first = conn_files[0]
        creds = Credentials(
            token=first["access_token"],
            refresh_token=first["refresh_token"],
        )

        for f in conn_files:
            google_file_id = f["google_file_id"]
            video_id = f["video_id"]
            file_name = f["file_name"]
            org_id = f["org_id"]

            # 1. Fetch createdTime from Google Drive
            created_time = fetch_created_time_from_drive(google_file_id, creds)
            if not created_time:
                logger.warning(f"  SKIP {video_id} ({file_name}) — no createdTime from Drive")
                failed += 1
                continue

            # 2. Update DB
            if update_db(video_id, created_time, db_url):
                logger.info(f"  DB_OK {video_id} ({file_name}) → {created_time}")
                db_updated += 1
            else:
                logger.info(f"  DB_SKIP {video_id} ({file_name}) — already set")

            # 3. Update OpenSearch scenes
            if update_opensearch(video_id, created_time, org_id):
                os_updated += 1

            # Rate limit: Google Drive API quota
            time.sleep(0.1)

    logger.info(
        f"Backfill complete: "
        f"DB={db_updated} updated, "
        f"OpenSearch={os_updated} updated, "
        f"{failed} failed, "
        f"{len(files)} total"
    )


if __name__ == "__main__":
    main()
