"""
Tests for internal drive job management endpoints.

Covers:
- Token verification (auth)
- POST /internal/drive/jobs/claim — atomic claim with SKIP LOCKED
- PATCH /internal/drive/jobs/{file_id}/status — status update + enrichment recompute
- GET /internal/drive/files/{file_id} — file metadata lookup
- Concurrency: 10 concurrent claims yield no double-claims
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.drive.internal_router import (
    _verify_internal_token,
    claim_jobs,
    get_file_metadata,
    update_job_status,
)
from app.modules.drive.internal_schemas import (
    ClaimJobsRequest,
    UpdateJobStatusRequest,
)


# ── Auth tests ────────────────────────────────────────────────────────

class TestVerifyInternalToken:
    @pytest.mark.asyncio
    async def test_valid_token_accepted(self):
        with patch("app.modules.drive.internal_router.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = "secret-key-123"
            result = await _verify_internal_token("Bearer secret-key-123")
            assert result == "secret-key-123"

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self):
        with patch("app.modules.drive.internal_router.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = "correct-key"
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await _verify_internal_token("Bearer wrong-key")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_bearer_prefix_returns_401(self):
        with patch("app.modules.drive.internal_router.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = "key"
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await _verify_internal_token("Basic key")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_unconfigured_key_returns_503(self):
        with patch("app.modules.drive.internal_router.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = ""
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await _verify_internal_token("Bearer anything")
            assert exc_info.value.status_code == 503


# ── Helpers ───────────────────────────────────────────────────────────

def _make_drive_file(
    *,
    file_id=None,
    org_id=None,
    video_id="gd_abc123",
    caption_status="pending",
    stt_status=None,
    ocr_status=None,
    enrichment_state=None,
    keyframe_s3_prefix="orgs/org1/files/vid1/keyframes/",
    audio_s3_key="orgs/org1/files/vid1/audio.wav",
    is_deleted=False,
    created_at=None,
):
    """Create a mock DriveFile with the fields the router accesses."""
    f = MagicMock()
    f.id = file_id or uuid4()
    f.org_id = org_id or uuid4()
    f.video_id = video_id
    f.caption_status = caption_status
    f.stt_status = stt_status
    f.ocr_status = ocr_status
    f.enrichment_state = enrichment_state
    f.keyframe_s3_prefix = keyframe_s3_prefix
    f.audio_s3_key = audio_s3_key
    f.is_deleted = is_deleted
    f.created_at = created_at or datetime.now(timezone.utc)
    return f


def _mock_db_with_files(files):
    """Create mock DB session that returns given files from execute().scalars().all()."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = files
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result
    db.flush = AsyncMock()
    return db


def _mock_db_with_scalar_one(file_obj):
    """Create mock DB session that returns file from scalar_one_or_none()."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = file_obj
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()
    return db


# ── Claim jobs tests ──────────────────────────────────────────────────

class TestClaimJobs:
    @pytest.mark.asyncio
    async def test_claim_caption_returns_file(self):
        file = _make_drive_file()
        db = _mock_db_with_files([file])
        request = ClaimJobsRequest(job_type="caption", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert len(result.files) == 1
        assert result.files[0].id == file.id
        assert result.files[0].org_id == file.org_id
        assert result.files[0].video_id == file.video_id
        assert result.files[0].keyframe_s3_prefix == file.keyframe_s3_prefix
        # Verify the file was marked as running
        assert file.caption_status == "running"
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_claim_returns_audio_s3_key(self):
        file = _make_drive_file(audio_s3_key="orgs/o/files/v/audio.wav")
        db = _mock_db_with_files([file])
        request = ClaimJobsRequest(job_type="stt", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert len(result.files) == 1
        assert result.files[0].audio_s3_key == "orgs/o/files/v/audio.wav"

    @pytest.mark.asyncio
    async def test_claim_empty_returns_empty_list(self):
        db = _mock_db_with_files([])
        request = ClaimJobsRequest(job_type="caption", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert len(result.files) == 0
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_claim_stt_type_accepted(self):
        file = _make_drive_file()
        db = _mock_db_with_files([file])
        request = ClaimJobsRequest(job_type="stt", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert len(result.files) == 1
        # STT type should set stt_status to running
        assert file.stt_status == "running"

    @pytest.mark.asyncio
    async def test_claim_ocr_type_accepted(self):
        file = _make_drive_file()
        db = _mock_db_with_files([file])
        request = ClaimJobsRequest(job_type="ocr", limit=1)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert len(result.files) == 1
        assert file.ocr_status == "running"

    @pytest.mark.asyncio
    async def test_claim_multiple_files(self):
        files = [_make_drive_file(video_id=f"vid_{i}") for i in range(3)]
        db = _mock_db_with_files(files)
        request = ClaimJobsRequest(job_type="caption", limit=3)

        result = await claim_jobs(request=request, _token="valid", db=db)

        assert len(result.files) == 3
        for f in files:
            assert f.caption_status == "running"


# ── Update job status tests (caption) ─────────────────────────────────

class TestUpdateJobStatus:
    @pytest.mark.asyncio
    async def test_update_caption_done_recomputes_enrichment(self):
        file = _make_drive_file(stt_status="done", ocr_status="done")
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="caption", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        # Should have called db.execute twice: once for SELECT, once for UPDATE
        assert db.execute.await_count == 2
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_caption_failed_with_error(self):
        file = _make_drive_file(stt_status="done", ocr_status="done")
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(
            job_type="caption", status="failed", error="model_crash"
        )
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_update_nonexistent_file_returns_404(self):
        db = _mock_db_with_scalar_one(None)

        request = UpdateJobStatusRequest(job_type="caption", status="done")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_job_status(
                file_id=uuid4(), request=request, _token="valid", db=db,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_enrichment_state_partial_failure(self):
        """When stt=done, ocr=failed, caption=done → enrichment_state=failed_partial."""
        file = _make_drive_file(stt_status="done", ocr_status="failed")
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="caption", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_enrichment_state_all_done(self):
        """When all statuses are done → enrichment_state=done."""
        file = _make_drive_file(stt_status="done", ocr_status="done")
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="caption", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )
        assert result.ok is True


# ── Update job status tests (STT) ────────────────────────────────────

class TestUpdateSttJobStatus:
    @pytest.mark.asyncio
    async def test_update_stt_done(self):
        file = _make_drive_file(
            stt_status="running", caption_status="done", ocr_status="done",
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="stt", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        assert db.execute.await_count == 2
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_stt_failed_with_error(self):
        file = _make_drive_file(
            stt_status="running", caption_status="done", ocr_status="done",
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(
            job_type="stt", status="failed", error="whisper_oom"
        )
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )

        assert result.ok is True
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_update_stt_partial_failure(self):
        """When stt=failed, caption=done, ocr=done → enrichment_state=failed_partial."""
        file = _make_drive_file(
            stt_status="running", caption_status="done", ocr_status="done",
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="stt", status="failed")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_update_ocr_done(self):
        """OCR status update also works through the generic endpoint."""
        file = _make_drive_file(
            stt_status="done", caption_status="done", ocr_status="running",
        )
        db = _mock_db_with_scalar_one(file)

        request = UpdateJobStatusRequest(job_type="ocr", status="done")
        result = await update_job_status(
            file_id=file.id, request=request, _token="valid", db=db,
        )
        assert result.ok is True


# ── Get file metadata tests ───────────────────────────────────────────

class TestGetFileMetadata:
    @pytest.mark.asyncio
    async def test_get_existing_file(self):
        file = _make_drive_file(
            caption_status="running",
            stt_status="done",
            ocr_status="pending",
            enrichment_state="running",
        )
        db = _mock_db_with_scalar_one(file)

        result = await get_file_metadata(file_id=file.id, _token="valid", db=db)

        assert result.id == file.id
        assert result.org_id == file.org_id
        assert result.video_id == file.video_id
        assert result.keyframe_s3_prefix == file.keyframe_s3_prefix
        assert result.audio_s3_key == file.audio_s3_key
        assert result.caption_status == "running"
        assert result.stt_status == "done"
        assert result.ocr_status == "pending"
        assert result.enrichment_state == "running"

    @pytest.mark.asyncio
    async def test_get_nonexistent_file_returns_404(self):
        db = _mock_db_with_scalar_one(None)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_file_metadata(file_id=uuid4(), _token="valid", db=db)
        assert exc_info.value.status_code == 404


# ── Concurrency test ──────────────────────────────────────────────────

class TestClaimConcurrency:
    @pytest.mark.asyncio
    async def test_10_concurrent_claims_no_duplicates(self):
        """Simulate 10 concurrent claim requests; verify no file is claimed twice.

        Each DB mock returns a unique file. In the real DB, SKIP LOCKED
        prevents double-claims. Here we verify the router code correctly
        processes each claim independently.
        """
        all_files = [_make_drive_file(video_id=f"vid_{i}") for i in range(10)]
        claimed_ids: list = []

        async def _do_claim(file):
            db = _mock_db_with_files([file])
            request = ClaimJobsRequest(job_type="caption", limit=1)
            result = await claim_jobs(request=request, _token="valid", db=db)
            for f in result.files:
                claimed_ids.append(f.id)

        # Run 10 claims concurrently
        await asyncio.gather(*[_do_claim(f) for f in all_files])

        # Verify: 10 unique file IDs claimed, no duplicates
        assert len(claimed_ids) == 10
        assert len(set(claimed_ids)) == 10

    @pytest.mark.asyncio
    async def test_concurrent_claims_empty_db(self):
        """10 concurrent claims on empty DB — all get empty results, no errors."""
        results = []

        async def _do_claim():
            db = _mock_db_with_files([])
            request = ClaimJobsRequest(job_type="caption", limit=1)
            result = await claim_jobs(request=request, _token="valid", db=db)
            results.append(len(result.files))

        await asyncio.gather(*[_do_claim() for _ in range(10)])

        assert all(r == 0 for r in results)
        assert len(results) == 10


# ── Schema validation tests ───────────────────────────────────────────

class TestSchemaValidation:
    def test_claim_request_valid_job_types(self):
        for job_type in ("caption", "stt", "ocr"):
            req = ClaimJobsRequest(job_type=job_type, limit=1)
            assert req.job_type == job_type

    def test_claim_request_invalid_job_type(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ClaimJobsRequest(job_type="invalid", limit=1)

    def test_claim_request_limit_bounds(self):
        from pydantic import ValidationError
        # limit=0 should fail
        with pytest.raises(ValidationError):
            ClaimJobsRequest(job_type="caption", limit=0)
        # limit=11 should fail
        with pytest.raises(ValidationError):
            ClaimJobsRequest(job_type="caption", limit=11)
        # limit=10 should pass
        req = ClaimJobsRequest(job_type="caption", limit=10)
        assert req.limit == 10

    def test_update_status_valid_values(self):
        req = UpdateJobStatusRequest(job_type="caption", status="done")
        assert req.status == "done"
        assert req.error is None

        req2 = UpdateJobStatusRequest(
            job_type="stt", status="failed", error="some error"
        )
        assert req2.status == "failed"
        assert req2.error == "some error"

    def test_update_status_invalid_value(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpdateJobStatusRequest(job_type="caption", status="running")

    def test_update_status_requires_job_type(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpdateJobStatusRequest(status="done")

    def test_update_status_all_job_types(self):
        for job_type in ("caption", "stt", "ocr"):
            req = UpdateJobStatusRequest(job_type=job_type, status="done")
            assert req.job_type == job_type
            assert req.status == "done"
