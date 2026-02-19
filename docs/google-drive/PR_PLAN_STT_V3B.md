# V3b Phase 3: STT Enrichment Worker — PR Plan

**Date:** 2026-02-19
**Branch:** `refactor/product-scope-alignment`
**Depends on:** V3b Phase 1 (c43216c, 8d90639) + V3b Phase 2 (35150c9, ba365ad)

## Commit Plan (3 atomic commits)

### Commit 1: `feat(drive-stt): add STT infrastructure — claim method, config flags, update_stt_enrichment_status`

**Files modified:**
- `services/api/app/modules/drive/repository.py` — Add `claim_stt_pending_files()` and `update_stt_enrichment_status()`
- `services/api/app/config.py` — Add STT config variables

**repository.py changes:**

```python
async def claim_stt_pending_files(self, limit: int = 1) -> list[DriveFile]:
    """Claim files ready for STT enrichment using SELECT FOR UPDATE SKIP LOCKED."""
    result = await self.session.execute(
        select(DriveFile)
        .where(
            DriveFile.enrichment_state.in_(["pending", "failed_partial"]),
            DriveFile.stt_status == "pending",
            DriveFile.audio_s3_key.isnot(None),
            DriveFile.is_deleted.is_(False),
        )
        .order_by(DriveFile.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    files = list(result.scalars().all())
    for f in files:
        f.stt_status = "running"
    if files:
        await self.session.flush()
    return files

async def update_stt_enrichment_status(
    self,
    file_id: UUID,
    stt_status: str,
    enrichment_error: Optional[str] = None,
) -> None:
    """Update STT status and recompute enrichment_state from stt+ocr."""
    result = await self.session.execute(
        select(DriveFile).where(DriveFile.id == file_id)
    )
    df = result.scalar_one()
    new_state = _compute_enrichment_state(stt_status, df.ocr_status)
    values = {
        "stt_status": stt_status,
        "enrichment_state": new_state,
        "enrichment_updated_at": func.now(),
    }
    if enrichment_error is not None:
        values["enrichment_error"] = enrichment_error
    await self.session.execute(
        update(DriveFile).where(DriveFile.id == file_id).values(**values)
    )
    await self.session.flush()
```

**config.py additions:**

```python
# --- STT enrichment worker ---
drive_stt_enabled: bool = False
drive_stt_model: str = "small"
drive_stt_language: str = "ko"
drive_stt_backend: str = "faster-whisper"
drive_stt_poll_interval_seconds: int = 30
drive_stt_concurrency: int = 1
drive_stt_max_audio_seconds: int = 3600
```

**Tests added in this commit:** None (infra only, tested by commit 3).

---

### Commit 2: `feat(drive-stt): add STT enrichment worker service with alignment, re-ingest, and Docker`

**Files created:**
```
services/drive-stt-worker/
├── src/
│   ├── __init__.py
│   ├── worker.py           # Polling loop (mirrors OCR worker)
│   └── tasks/
│       ├── __init__.py
│       └── stt.py          # STT job processing
├── Dockerfile
└── pyproject.toml
```

**Files modified:**
- `docker-compose.yml` — Add `drive-stt-worker` service

#### Folder Layout

```
services/drive-stt-worker/
├── src/
│   ├── __init__.py          # empty
│   ├── worker.py            # APScheduler polling loop
│   │   ├── poll_and_process()   # single poll cycle
│   │   ├── main()               # entry point
│   │   ├── _acquire_slot()      # concurrency control
│   │   └── _release_slot()
│   └── tasks/
│       ├── __init__.py      # empty
│       └── stt.py           # STT job logic
│           ├── process_stt_pending_files()     # claim + dispatch
│           ├── _process_single_stt()           # download, transcribe, align, re-ingest
│           ├── _get_audio_duration_seconds()    # WAV header duration check
│           ├── _align_segments_to_scenes()      # wrapper around contracts alignment
│           └── _post_scenes_to_api()            # HTTP POST to internal ingest
├── Dockerfile
└── pyproject.toml
```

#### Dockerfile Strategy

```dockerfile
FROM python:3.11-slim

# No special system deps for faster-whisper (pure Python + CTranslate2 binary wheel)
# Unlike OCR worker, no libgl1/libglib2.0 needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .
COPY src/ src/

RUN useradd -m -u 1000 appuser
USER appuser

CMD ["python", "-m", "src.worker"]
```

Key design decisions:
- **No model download during build** — model cache is a Docker volume mount
- **No ffmpeg** — audio already extracted in Phase 1 (WAV on S3)
- **faster-whisper downloads models lazily** — first transcription triggers download
  into the cache volume, subsequent runs use cache

#### pyproject.toml

```toml
[project]
name = "heimdex-drive-stt-worker"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "psycopg2-binary>=2.9",
    "boto3>=1.34",
    "apscheduler>=3.10,<4",
    "pydantic-settings>=2.0",
    "structlog>=23.0",
    "requests>=2.31",
    "faster-whisper>=1.0",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends._legacy:_Backend"
```

#### docker-compose.yml addition

```yaml
drive-stt-worker:
  build:
    context: ./services/drive-stt-worker
    dockerfile: Dockerfile
  container_name: heimdex-drive-stt-worker
  environment:
    - PYTHONPATH=/app:/opt/heimdex-api
    - DATABASE_URL=${DATABASE_URL:-postgresql+asyncpg://heimdex:heimdex_dev_password@postgres:5432/heimdex}
    - DATABASE_URL_SYNC=${DATABASE_URL_SYNC:-postgresql://heimdex:heimdex_dev_password@postgres:5432/heimdex}
    - MINIO_ENDPOINT=minio:9000
    - MINIO_ACCESS_KEY=${MINIO_ACCESS_KEY:-heimdex}
    - MINIO_SECRET_KEY=${MINIO_SECRET_KEY:-heimdex_dev_password}
    - MINIO_SECURE=${MINIO_SECURE:-false}
    - DRIVE_STT_ENABLED=${DRIVE_STT_ENABLED:-false}
    - DRIVE_STT_MODEL=${DRIVE_STT_MODEL:-small}
    - DRIVE_STT_LANGUAGE=${DRIVE_STT_LANGUAGE:-ko}
    - DRIVE_STT_BACKEND=${DRIVE_STT_BACKEND:-faster-whisper}
    - DRIVE_INTERNAL_API_KEY=${DRIVE_INTERNAL_API_KEY:-}
    - DRIVE_API_BASE_URL=http://api:8000
    - DRIVE_S3_BUCKET=${DRIVE_S3_BUCKET:-heimdex-drive}
    - DRIVE_STT_POLL_INTERVAL_SECONDS=${DRIVE_STT_POLL_INTERVAL_SECONDS:-30}
    - DRIVE_STT_CONCURRENCY=${DRIVE_STT_CONCURRENCY:-1}
    - DRIVE_STT_MAX_AUDIO_SECONDS=${DRIVE_STT_MAX_AUDIO_SECONDS:-3600}
    - LOG_LEVEL=${LOG_LEVEL:-INFO}
  volumes:
    - ./services/drive-stt-worker:/app
    - ./services/api:/opt/heimdex-api:ro
    - ../heimdex-media-contracts:/opt/heimdex-media-contracts:ro
    - ../heimdex-media-pipelines:/opt/heimdex-media-pipelines:ro
    - whisper_model_cache:/data/whisper-models
  depends_on:
    postgres:
      condition: service_healthy
    minio:
      condition: service_healthy
    api:
      condition: service_healthy
  command: >
    sh -c "pip install --no-deps -e /opt/heimdex-media-contracts 2>/dev/null;
           pip install --no-deps -e /opt/heimdex-media-pipelines 2>/dev/null;
           python -m src.worker"
```

Note: `whisper_model_cache` volume added to `volumes:` section.

#### Config/Env Vars

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DRIVE_STT_ENABLED` | bool | `false` | Feature gate — container sleeps when false |
| `DRIVE_STT_MODEL` | str | `"small"` | Whisper model name (tiny/base/small/medium/large-v3) |
| `DRIVE_STT_LANGUAGE` | str | `"ko"` | Language code for STT |
| `DRIVE_STT_BACKEND` | str | `"faster-whisper"` | STT backend (faster-whisper/whisper/api) |
| `DRIVE_STT_POLL_INTERVAL_SECONDS` | int | `30` | Polling interval |
| `DRIVE_STT_CONCURRENCY` | int | `1` | Max concurrent STT jobs |
| `DRIVE_STT_MAX_AUDIO_SECONDS` | int | `3600` | Hard cap on audio duration |

#### DB Job Claiming Query

```sql
SELECT *
FROM drive_files
WHERE enrichment_state IN ('pending', 'failed_partial')
  AND stt_status = 'pending'
  AND audio_s3_key IS NOT NULL
  AND is_deleted = FALSE
ORDER BY created_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED
```

Then immediately: `UPDATE drive_files SET stt_status = 'running' WHERE id = ?`

#### State Transitions

```
stt_status: pending → running → done     (success path)
stt_status: pending → running → failed   (error path)
```

- On success: `stt_status="done"`, recompute `enrichment_state`
- On failure: `stt_status="failed"`, set `enrichment_error`, recompute `enrichment_state`
- No retry within STT worker — Phase 1 already has `retry_count` / `max_retries` on DriveFile for the main pipeline

#### Failure Isolation

- STT failure → `stt_status="failed"`, `enrichment_state="failed_partial"` (if OCR succeeded) or `"failed"` (if OCR also failed)
- STT failure does NOT affect:
  - OCR enrichment (independent worker, independent status)
  - Basic scene indexing (scenes already indexed by initial ingest)
  - Scene timing, thumbnails, or OCR text
- The scene is still searchable by OCR text and metadata even if STT fails

---

### Commit 3: `test(drive-stt): add alignment, payload, and config tests`

**Files created:**
- `services/api/tests/test_stt_segment_alignment.py` — alignment logic tests
- `services/api/tests/test_stt_ingest_payload.py` — payload construction tests
- `services/api/tests/test_stt_worker_config.py` — config defaults + enrichment state tests

#### Test Plan

**test_stt_segment_alignment.py** (~12 tests):
- Segment fully within one scene → assigned correctly
- Segment spanning two scenes → assigned to scene with more overlap
- Segment before all scenes → not assigned
- Segment after all scenes → not assigned
- No segments → all scenes get empty transcript
- One segment covering entire video → assigned to scene with most overlap
- Multiple segments in same scene → concatenated in time order
- Single scene, multiple segments → all assigned
- Empty text segments → included in count but no text contribution
- Overlapping segments → each independently assigned
- Audio duration guard: under limit passes, over limit rejects
- WAV duration reading from real header

**test_stt_ingest_payload.py** (~5 tests):
- Updated scenes include transcript_raw from alignment
- speech_segment_count matches assigned count
- Existing OCR fields preserved in re-ingest payload
- Scenes with no assigned segments get empty transcript
- transcript_raw truncation at 50k chars (Pydantic validation)

**test_stt_worker_config.py** (~7 tests):
- STT disabled by default
- Default model is "small"
- Default language is "ko"
- Default backend is "faster-whisper"
- Default concurrency is 1
- Default poll interval is 30
- Default max audio seconds is 3600

#### Test Import Pattern

Same `importlib.util.spec_from_file_location()` pattern as OCR tests
to avoid namespace pollution:

```python
import importlib.util
from pathlib import Path

_stt_module_path = (
    Path(__file__).resolve().parents[2] / "drive-stt-worker" / "src" / "tasks" / "stt.py"
)
_spec = importlib.util.spec_from_file_location("_stt_tasks_for_test", _stt_module_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_get_audio_duration_seconds = _mod._get_audio_duration_seconds
```

For alignment tests, import directly from contracts (already in PYTHONPATH):
```python
from heimdex_media_contracts.scenes.merge import assign_segments_to_scenes, aggregate_transcript
from heimdex_media_contracts.scenes.schemas import SceneBoundary
from heimdex_media_contracts.speech.schemas import SpeechSegment
```

---

## Verification Checklist

- [ ] All existing tests pass (baseline: 648 passed, 10 skipped)
- [ ] New tests pass (~24 tests added)
- [ ] `lsp_diagnostics` clean on all changed files (pre-existing errors excluded)
- [ ] No changes to agent ingestion behavior
- [ ] No OpenSearch calls from worker
- [ ] STT worker is scene-centric and idempotent
- [ ] Feature-gated behind `DRIVE_STT_ENABLED=false`

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| faster-whisper model download on first run | Document in runbook; model cache volume persists |
| Long STT processing time (3-5min for 10min audio) | `DRIVE_STT_CONCURRENCY=1` default, configurable |
| OOM on large audio files | `DRIVE_STT_MAX_AUDIO_SECONDS=3600` hard cap |
| Alignment produces empty transcripts | Acceptable — scene still searchable by OCR |
| Re-ingest overwrites OCR text | No — manifest preserves all fields, STT only adds `transcript_raw` |
