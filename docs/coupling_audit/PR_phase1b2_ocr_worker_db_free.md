# Phase 1b-2: OCR Worker DB-Free

## Summary

Decouples `drive-ocr-worker` from direct database access, completing the enrichment-worker trilogy (caption → STT → OCR). The OCR worker now communicates with the API server exclusively via the existing internal HTTP endpoints using `InternalAPIClient` from the worker SDK.

No API schema or endpoint changes were required — the generalized internal API from Phase 1b-1 already supports `job_type="ocr"` for claim, status update, and error column mapping.

## What Changed

### OCR Worker: DB Removed

**Modified files:**
- `src/worker.py` — Replaced `create_async_engine` + `async_sessionmaker` with `InternalAPIClient`
- `src/tasks/ocr.py` — Replaced all `DriveFileRepository` calls with `api_client` HTTP calls

**Replaced patterns:**

| Before (DB) | After (HTTP) |
|-------------|-------------|
| `file_repo.claim_ocr_pending_files(limit=1)` | `api_client.claim_jobs("ocr", limit=1)` |
| `file_repo.update_enrichment_status(file_id, ocr_status="done")` | `api_client.update_job_status(file_id, job_type="ocr", status="done")` |
| `file_repo.update_enrichment_status(file_id, ocr_status="failed", enrichment_error=msg)` | `api_client.update_job_status(file_id, job_type="ocr", status="failed", error=msg)` |
| `async with session_factory() as session:` + `session.commit()` / `session.rollback()` | (removed — no DB session needed) |
| `importlib.import_module("app.db.models")` | (removed — no model registration needed) |
| `importlib.import_module("app.modules.drive.repository")` | (removed — no repository access) |

**Removed from OCR worker:**
- SQLAlchemy engine/session creation
- `app.db.models` import
- `app.modules.drive.repository` import
- All `session.commit()` / `session.rollback()` calls
- `session` and `file_repo` parameters on `_process_single_ocr`

**`_process_single_ocr` changed from `async def` to `def`** — no more `await` calls since `api_client.update_job_status()` is synchronous (uses `requests` library).

**Unchanged:** S3 artifact behavior (manifest + keyframe downloads), OCR engine processing, `/internal/ingest/enrich` POST for OCR data.

### API: No Changes

The generalized internal API from Phase 1b-1 already supports OCR:
- `POST /internal/drive/jobs/claim` with `job_type="ocr"` — claims files with `keyframe_s3_prefix IS NOT NULL` prerequisite
- `PATCH /internal/drive/jobs/{file_id}/status` with `job_type="ocr"` — maps error to `enrichment_error` column
- Error column mapping: `ocr → enrichment_error` (shared with STT, as designed)

### Docker Compose: OCR Worker Only

**Removed:**
- `DATABASE_URL` and `DATABASE_URL_SYNC` env vars
- `/opt/heimdex-api` from PYTHONPATH
- `./services/api:/opt/heimdex-api:ro` volume mount
- `postgres` from `depends_on`

**Kept:** `drive-worker` unchanged (still has DB access).

### Dockerfile & pyproject.toml

**Removed dependencies:** `sqlalchemy[asyncio]`, `asyncpg`, `psycopg2-binary`

## Verification Gates

| Gate | Result |
|------|--------|
| `grep create_async_engine` in ocr-worker | Zero matches |
| `grep async_sessionmaker` in ocr-worker | Zero matches |
| `grep app.db` in ocr-worker | Zero matches |
| `grep app.modules.drive.repository` in ocr-worker | Zero matches |
| `grep sqlalchemy` in ocr-worker | Zero matches |
| `grep asyncpg\|psycopg` in ocr-worker | Zero matches |
| `grep DATABASE_URL` in ocr-worker | Zero matches |
| `grep DATABASE_URL` in docker-compose (ocr section) | Zero matches |
| Internal drive router tests | 30 passed |
| Worker SDK tests | 26 passed |

## Test Coverage

No new tests needed — the internal API was already generalized and tested for OCR in Phase 1b-1:
- **30 API tests** include `test_claim_ocr_type_accepted` and `test_update_ocr_done`
- **26 SDK tests** include `test_update_ocr_success`
- Concurrency, retry, backoff, auth tests all cover OCR path implicitly

## Files Modified

```
services/drive-ocr-worker/src/worker.py        # Remove DB, use InternalAPIClient
services/drive-ocr-worker/src/tasks/ocr.py      # Replace repository calls with HTTP
services/drive-ocr-worker/pyproject.toml        # Remove sqlalchemy/asyncpg deps
services/drive-ocr-worker/Dockerfile             # Remove sqlalchemy/asyncpg from fallback install
docker-compose.yml                               # OCR worker: remove DB env/volume/depends
docs/coupling_audit/PR_phase1b2_ocr_worker_db_free.md  # This file
```

## Rollback Plan

1. `git revert <commit-hash>` — single commit, clean revert
2. `docker-compose up -d --build drive-ocr-worker` — rebuild with DB deps restored
3. No database migration to undo — no schema changes were made
4. Other workers (caption, STT, drive-worker) are unaffected

## DB-Free Worker Status

| Worker | Status | Phase |
|--------|--------|-------|
| drive-caption-worker | ✅ DB-free | 1a |
| drive-stt-worker | ✅ DB-free | 1b-1 |
| drive-ocr-worker | ✅ DB-free | 1b-2 |
| drive-worker | ❌ Still uses DB | TBD |

## Next Steps

- Migrate `drive-worker` (main sync worker) — most complex, needs additional endpoints for file creation, connection management, and sync state
- Once all workers are DB-free, remove `database_url` from `WorkerSettings`