# Internal API Hardening: Lease Tokens

## Summary

Strengthens the internal drive job protocol with lease-based ownership, idempotency guards, and structured observability. Every claimed job now receives a UUID lease token with a 10-minute expiry. Status updates must present the matching token or receive a 409 Conflict.

## Problem

Without leases, a worker that crashes mid-processing leaves the job in `running` state forever. If two workers somehow claim the same file (e.g., after a container restart racing with a re-queue), both can write status updates, causing data corruption. There is no way to detect stale workers or enforce single-owner semantics.

## Changes

### DB Schema (additive only)
- Migration `020_add_lease_token_columns`: adds `lease_token` (String(36), nullable) and `lease_expires_at` (DateTime TZ, nullable) to `drive_files`.
- Model: corresponding `Mapped[Optional[...]]` columns on `DriveFile`.

### API Router (`internal_router.py`)
- **Claim endpoint**: generates a UUID `lease_token` and sets `lease_expires_at = now + 600s` for each claimed file. WHERE clause now includes `(lease_token IS NULL OR lease_expires_at < now)` to prevent claiming actively-leased files.
- **Status update endpoint**:
  - Lease enforcement: if the file has a `lease_token`, the request must include a matching `lease_token` and the lease must not be expired. Mismatches → 409.
  - Idempotency: re-sending the same terminal status (done→done, failed→failed) returns `ok: true` without issuing an UPDATE.
  - On successful update, clears `lease_token` and `lease_expires_at`.
- **Structured logging**: all 3 endpoints now log `latency_ms`, masked `lease_token` (last 6 chars), file counts, and operation results.

### Schemas (`internal_schemas.py`)
- `ClaimedFileInfo`: added `lease_token: str` and `lease_expires_at: datetime`.
- `UpdateJobStatusRequest`: added `lease_token: Optional[str] = None`.

### SDK (`internal_api.py`)
- `ClaimedFile` dataclass: added `lease_token` and `lease_expires_at` fields.
- `update_job_status()`: accepts `lease_token` kwarg, includes in payload when present.
- `claim_jobs()`: parses `lease_token` and `lease_expires_at` from response.

### Workers (caption, stt, ocr)
- Each `_process_single_*` function extracts `lease_token = claimed_file.lease_token` and passes it to every `api_client.update_job_status()` call (21 call sites total across 3 workers).

## Backward Compatibility

- All changes are additive. The `lease_token` field on `UpdateJobStatusRequest` defaults to `None`.
- Files with no `lease_token` (pre-existing rows) skip lease enforcement entirely.
- No external API changes. Only `/internal/drive/*` endpoints are affected.
- Migration is safe: both columns are nullable with no default values.

## Test Coverage

| Suite | Count | Description |
|-------|-------|-------------|
| Router | 46 | Auth, claim, lease tokens, lease enforcement, idempotency, metadata, concurrency, schema validation |
| SDK | 31 | Claim parsing, lease fields, update payloads, retry behavior, backoff |

### New test classes:
- `TestClaimLeaseTokens` (5 tests): lease token assigned, unique per file, expiry in future
- `TestLeaseEnforcement` (5 tests): matching token accepted, wrong token 409, missing token 409, expired 409, no-lease bypass
- `TestIdempotency` (3 tests): done-on-done safe, failed-on-failed safe, done-on-failed updates
- SDK lease tests (5 tests): parse lease fields, send lease_token, omit when None, with error+lease

## Files Changed

| File | Change |
|------|--------|
| `services/api/app/modules/drive/models.py` | +2 columns: `lease_token`, `lease_expires_at` |
| `services/api/app/db/migrations/versions/020_add_lease_token_columns.py` | New migration |
| `services/api/app/modules/drive/internal_router.py` | Lease generation, validation, idempotency, structured logging |
| `services/api/app/modules/drive/internal_schemas.py` | Lease fields on `ClaimedFileInfo` + `UpdateJobStatusRequest` |
| `services/worker_sdk/src/heimdex_worker_sdk/internal_api.py` | `ClaimedFile` + `update_job_status` lease support |
| `services/drive-caption-worker/src/tasks/caption.py` | Lease token passthrough (7 call sites) |
| `services/drive-stt-worker/src/tasks/stt.py` | Lease token passthrough (7 call sites) |
| `services/drive-ocr-worker/src/tasks/ocr.py` | Lease token passthrough (7 call sites) |
| `services/api/tests/test_internal_drive_router.py` | 46 tests (was 30, +16 new) |
| `services/worker_sdk/tests/test_internal_api.py` | 31 tests (was 26, +5 new) |
| `docs/coupling_audit/PR_internal_api_hardening_leases.md` | This document |

## Next Steps

- Deploy and run `alembic upgrade head` on staging
- Monitor lease enforcement logs for any worker-side issues
- Consider: lease renewal endpoint for long-running jobs (>10 min)
- Consider: dead-letter queue for jobs that fail lease validation repeatedly
- Phase 2: migrate `drive-worker` to use the internal API (separate PR)
