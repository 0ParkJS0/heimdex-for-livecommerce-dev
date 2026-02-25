# Housekeeping Findings — Post-GPU-Migration Audit

**Date**: 2026-02-26
**Auditor**: Sisyphus (automated, verified via SSH + codebase search)
**Scope**: `dev-heimdex-for-livecommerce`, `infra/deploy/`, `docs/`, `scripts/`, staging EC2

---

## 1. Executive Summary

Heimdex enrichment workers (STT, OCR, Caption) have migrated from CPU containers on a staging EC2 instance to GPU containers on Aircloud+, consuming jobs via AWS SQS. The `drive-worker` (Google Drive discovery + processing) remains on EC2.

The codebase is currently at **Phase 3** of the SQS migration plan (`docs/queue_arch/06_migration_plan.md`). Phase 4 ("Cleanup") has not been executed. This audit identifies all stale artifacts left over from Phases 0–2 and the pre-SQS HTTP-polling era.

**Key risks found:**
1. **Dual SQS consumer conflict**: EC2 enrichment workers share the same SQS queues as Aircloud+ workers. `deploy-staging.yml` rebuilds and restarts EC2 workers on every push to `main`, causing competing consumers.
2. **Config drift**: EC2 `.env` diverged from the repo's `config.env` in critical variables (`SQS_CONSUMER_ENABLED`, `MINIO_ENDPOINT`, model choices).
3. **Dead services on EC2**: `face-worker` (sleep infinity), `llama-caption-server` (running but unused by Aircloud+ which uses `qwen2vl`).
4. **Deprecated settings still wired**: `DRIVE_*_POLL_INTERVAL_SECONDS` vars in docker-compose, settings, and tests.

---

## 2. Architecture — Current State

```
                        ┌─────────────────────────────────────┐
                        │          AWS SQS (Seoul)            │
                        │  processing / caption / stt / ocr   │
                        └──────┬───────────────┬──────────────┘
                   publish     │               │  consume
                   (API)       │               │  (long-poll)
                               │               │
┌──────────────────────────────┼───┐   ┌───────┼──────────────────────┐
│  Staging EC2 (3.34.75.63)    │   │   │  Aircloud+ GPU Workers      │
│                              │   │   │                              │
│  ┌─────────┐  ┌───────────┐ │   │   │  caption-worker-gpu (Qwen2)  │
│  │ Postgres │  │ OpenSearch│ │   │   │  stt-worker-gpu (turbo/cuda) │
│  └─────────┘  └───────────┘ │   │   │  ocr-worker-gpu (PaddleGPU)  │
│  ┌─────────┐  ┌───────────┐ │   │   │                              │
│  │  Nginx  │  │    API    │─┘   │   │  Images: ghcr.io/jlee-heimdex│
│  └─────────┘  └───────────┘     │   │          /heimdex-*-gpu:latest│
│  ┌─────────┐  ┌───────────┐     │   └──────────────────────────────┘
│  │   Web   │  │drive-worker│    │
│  └─────────┘  └───────────┘     │
│               (discovery poll   │
│                + SQS consumer)  │
│                                 │
│  STOPPED (exit 137):            │
│  drive-stt-worker               │
│  drive-ocr-worker               │
│  drive-caption-worker           │
│  face-worker (sleep infinity)   │
│                                 │
│  RUNNING (unused by Aircloud+): │
│  llama-caption-server           │
└─────────────────────────────────┘
```

---

## 3. Worker Execution Path Inventory

### 3.1 Current SQS Consumer Path (PRIMARY)

All enrichment workers use `SQSConsumerLoop` from `worker_sdk`. No legacy HTTP polling remains in enrichment worker code — they `sys.exit(1)` if SQS is not configured.

| Worker | Entrypoint | SQS Queue | Requires SQS? | Fallback? |
|--------|-----------|-----------|---------------|-----------|
| drive-worker | `services/drive-worker/src/worker.py` | `sqs_processing_queue_url` | Yes (`sys.exit(1)`) | None — SQS required |
| drive-caption-worker | `services/drive-caption-worker/src/worker.py` | `sqs_caption_queue_url` | Yes (`sys.exit(1)`) | None |
| drive-stt-worker | `services/drive-stt-worker/src/worker.py` | `sqs_stt_queue_url` | Yes (`sys.exit(1)`) | None |
| drive-ocr-worker | `services/drive-ocr-worker/src/worker.py` | `sqs_ocr_queue_url` | Yes (`sys.exit(1)`) | None |

### 3.2 APScheduler Discovery Path (drive-worker only)

`drive-worker` retains `AsyncIOScheduler` for Google Drive discovery polling (`poll_and_discover`, 30s interval). This is **not** a processing path — it discovers new files which the API then publishes to SQS. This must remain active.

### 3.3 Deprecated Paths (code removed, config remnants)

The enrichment workers previously used HTTP polling (`claim_enrichment` API endpoints + APScheduler). This code was removed in the SQS migration but the following config remnants persist:

| Setting | Location | Status |
|---------|----------|--------|
| `DRIVE_CAPTION_POLL_INTERVAL_SECONDS` | docker-compose.yml:354, settings.py:57, config.py:152 | **Deprecated** (comment says so) |
| `DRIVE_STT_POLL_INTERVAL_SECONDS` | docker-compose.yml:407, settings.py:69, config.py:146 | **Deprecated** |
| `DRIVE_OCR_POLL_INTERVAL_SECONDS` | docker-compose.yml:281, settings.py:75, config.py:136 | **Deprecated** |
| Tests asserting defaults | test_stt_worker_config.py:26, test_caption_enrichment.py:13, test_ocr_worker_job_claiming.py:52 | **Stale** |

---

## 4. Stale Artifact Inventory

### 4.1 EC2 Enrichment Worker Containers (CRITICAL)

**Files**: `docker-compose.yml` lines 263–430 (drive-ocr-worker, drive-caption-worker, drive-stt-worker services)

**Evidence**: These containers on EC2 consume from the **same SQS queues** as Aircloud+ GPU workers:
- EC2 `.env`: `SQS_CONSUMER_ENABLED=true`, `SQS_CAPTION_QUEUE_URL=...heimdex-caption-queue`
- Aircloud+: `SQS_CONSUMER_ENABLED=true`, `SQS_CAPTION_QUEUE_URL=...heimdex-caption-queue`

**Current state**: EC2 containers are `Exited (137)` (manually killed ~4 hours before audit). But `deploy-staging.yml` will **rebuild and restart them** on next push to `main` (lines 114–119).

**Risk**: Dual consumers fighting over messages. EC2 workers run on CPU (slower) and would steal work from GPU workers.

### 4.2 deploy-staging.yml Worker Restart Block

**File**: `.github/workflows/deploy-staging.yml` lines 114–119
```yaml
if [ "$WORKER_CHANGED" = true ] || [ "$API_CHANGED" = true ]; then
  echo "--- rebuilding and restarting enrichment workers ---"
  docker compose build drive-stt-worker drive-ocr-worker drive-caption-worker
  docker compose up -d --no-deps --force-recreate drive-stt-worker drive-ocr-worker drive-caption-worker
  sleep 5
fi
```

**Problem**: Every API change triggers a rebuild and restart of EC2 enrichment workers, creating dual consumers.

### 4.3 face-worker Service

**File**: `docker-compose.yml` lines 195–210
**Evidence**: Command is `sleep infinity`. No references to face-worker in any workflow or active code path. Image is 6.37GB. Container always exits with 137 on EC2.
**Status**: Dead code.

### 4.4 llama-caption-server

**File**: `docker-compose.yml` lines 305–334, `services/llama-caption-server/`
**Evidence**: Running on EC2 (healthy, 4 days uptime). But Aircloud+ caption worker uses `CAPTION_ENGINE=qwen2vl`, not `llama_http`. EC2 config still has `CAPTION_ENGINE=llama_http`.
**Status**: Unused by Aircloud+ workers. May still be used by EC2 caption worker when it was running.

### 4.5 CPU Dockerfiles (non-GPU)

| File | Purpose | Status |
|------|---------|--------|
| `services/drive-caption-worker/Dockerfile` | CPU caption worker | Used by docker-compose (local dev + EC2 staging) |
| `services/drive-stt-worker/Dockerfile` | CPU STT worker | Same |
| `services/drive-ocr-worker/Dockerfile` | CPU OCR worker | Same |

**Note**: These are still needed for local `docker compose up` development. They should NOT be deleted. But they should be clearly labeled as dev-only.

### 4.6 Deprecated Poll Interval Settings

Already listed in section 3.3 above. These settings are declared with `# DEPRECATED (Phase 3)` comments in `worker_sdk/settings.py` but remain wired in:
- `docker-compose.yml` (4 env vars passed to workers)
- `api/app/config.py` (4 field declarations)
- 3 test files asserting default values

### 4.7 ElasticMQ on EC2

**Evidence**: `heimdex-elasticmq` container running on EC2 (29 hours uptime).
**Purpose**: SQS mock for local development.
**Status on EC2**: Unnecessary. EC2 workers use real SQS (queue URLs point to `sqs.ap-northeast-2.amazonaws.com`). ElasticMQ is only needed for local `docker compose up` with `SQS_ENDPOINT_URL=http://elasticmq:9324`.

### 4.8 `apscheduler` Dependency in GPU Dockerfiles

All three `Dockerfile.gpu` files install `apscheduler>=3.10,<4`:
- `services/drive-caption-worker/Dockerfile.gpu` line 57
- `services/drive-stt-worker/Dockerfile.gpu` line 52
- `services/drive-ocr-worker/Dockerfile.gpu` line 55

**Evidence**: Enrichment workers do NOT use APScheduler — they are pure SQS consumers. Only `drive-worker` uses APScheduler for discovery polling, and there is no `drive-worker/Dockerfile.gpu`.

---

## 5. Staging EC2 Findings

### 5.1 SSH Inspection Summary

**SSH target**: `ec2-user@3.34.75.63` via `~/.ssh/heimdex-staging.pem`
**Inspection date**: 2026-02-26 04:50 KST

| Check | Result |
|-------|--------|
| Systemd worker units | None found |
| Cron (root) | None |
| Cron (ec2-user) | None |
| `/etc/cron.d/` | Only `certbot-renew` |
| Worker processes outside Docker | None |
| `.env` location | `/opt/heimdex/.env` (symlinked to `dev-heimdex-for-livecommerce/.env`) |
| Disk usage | 47G / 200G (24%) |
| Memory | 4.1G used / 15G total, 2G swap used |

### 5.2 Running Containers

| Container | Status | Needed? |
|-----------|--------|---------|
| heimdex-api | Up 26min (healthy) | **YES** — serves API for Aircloud+ workers |
| heimdex-web | Up 6hr | **YES** — serves frontend |
| heimdex-postgres | Up 3 days (healthy) | **YES** — primary database |
| heimdex-opensearch | Up 3 days (healthy) | **YES** — search index |
| heimdex-minio | Up 3 days (healthy) | **INVESTIGATE** — EC2 .env has `MINIO_ENDPOINT=` (empty), real S3 used. MinIO may be vestigial. |
| heimdex-drive-worker | Up 3hr | **YES** — Google Drive discovery polling |
| heimdex-llama-caption | Up 4 days (healthy) | **NO** — Aircloud+ uses qwen2vl, not llama_http |
| heimdex-elasticmq | Up 29hr | **NO** — SQS mock, real SQS is used |
| heimdex-drive-stt-worker | Exited (137) | **NO** — replaced by Aircloud+ GPU |
| heimdex-drive-ocr-worker | Exited (137) | **NO** — replaced by Aircloud+ GPU |
| heimdex-drive-caption-worker | Exited (137) | **NO** — replaced by Aircloud+ GPU |
| heimdex-face-worker | Exited (137) | **NO** — dead code, sleep infinity |

### 5.3 What EC2 Still Provides

EC2 remains the **control plane** for Heimdex staging:
- **API** (FastAPI): receives ingest, serves search, publishes to SQS, handles drive OAuth
- **Web** (Next.js): customer-facing frontend
- **Postgres**: primary relational database
- **OpenSearch**: scene search index
- **Nginx**: TLS termination, reverse proxy, rate limiting
- **drive-worker**: Google Drive discovery polling + SQS processing consumer

EC2 is NOT replaceable by Aircloud+ — Aircloud+ only runs stateless GPU workers.

---

## 6. Config Drift Analysis

### 6.1 EC2 .env vs Repo config.env

| Variable | EC2 .env (live) | Repo config.env | Impact |
|----------|----------------|-----------------|--------|
| `SQS_CONSUMER_ENABLED` | `true` | `false` | **CRITICAL** — repo template would disable SQS consumers |
| `MINIO_ENDPOINT` | `` (empty) | `none` | Functionally equivalent (both trigger real S3 mode) |
| `MINIO_ACCESS_KEY` | `heimdex` | `` (empty) | EC2 has credentials; not used when MINIO_ENDPOINT is empty |
| `MINIO_SECRET_KEY` | `mClLhnNm7SSY...` | `` (empty) | Same as above |
| `S3_REGION` | `ap-northeast-2` (at end) | Not present | Missing from config.env template |
| `SQS_CONSUMER_ENABLED` | `true` (added 2026-02-25) | `false` | Recently added to EC2, not reflected in repo |

### 6.2 EC2 vs Aircloud+ Worker Config

| Variable | EC2 Workers | Aircloud+ Workers | Notes |
|----------|------------|-------------------|-------|
| `DRIVE_API_BASE_URL` | `http://api:8000` (docker network) | `https://devorg.app.heimdexdemo.dev` (public) | Expected — Aircloud+ can't reach docker network |
| `CAPTION_ENGINE` | `llama_http` | `qwen2vl` | Different models! EC2 used llama.cpp sidecar |
| `DRIVE_CAPTION_MODEL` | `OpenGVLab/InternVL2-1B` (config.env) | `Qwen/Qwen2-VL-2B-Instruct` | Different model |
| `DRIVE_STT_MODEL` | `small` | `turbo` | Aircloud+ uses larger model (GPU enables this) |
| `STT_DEVICE` | `cpu` (default) | `cuda` | GPU acceleration |
| `STT_COMPUTE_TYPE` | `int8` (default) | `float16` | GPU precision |
| `USE_GPU` | `false` (default) | `true` | GPU flag |
| AWS auth | IAM Role (`heimdex-staging-ec2`) | Explicit keys (`AKIA26IUJPAM...`) | Different auth mechanisms |

---

## 7. CI/CD Inventory

| Workflow | Repo | Target | Status | Action Needed |
|----------|------|--------|--------|---------------|
| `deploy-staging.yml` | SaaS | EC2 (SSH) | **ACTIVE** | Remove enrichment worker build/restart block |
| `build-gpu-images.yml` | SaaS | GHCR | **ACTIVE** | Keep — builds images for Aircloud+ |
| `worker-coupling-check.yml` | SaaS | PR gate | **ACTIVE** | Keep |
| `search-quality.yml` | SaaS | PR gate | **ACTIVE** | Keep |
| `deploy-staging.yml` | Pipelines | EC2 (SSH) | **ACTIVE** | Remove enrichment worker restart |
| `release.yml` | Contracts | PyPI | **ACTIVE** | Keep |
| `release.yml` | Pipelines | PyPI | **ACTIVE** | Keep |
| `release.yml` | Agent | S3 | **ACTIVE** | Keep |

---

## 8. Migration Phase Status

Per `docs/queue_arch/06_migration_plan.md`:

| Phase | Name | Status | Evidence |
|-------|------|--------|----------|
| Phase 0 | Infrastructure Foundation | **DONE** | ElasticMQ in compose, SQS client in SDK, settings wired |
| Phase 1 | Dual-Write Producer | **DONE** | `sqs_producer.py` publishes on status changes when `SQS_ENABLED=true` |
| Phase 2 | Dual-Read Consumer | **DONE** | Workers have SQS consumer; but HTTP polling code is already removed |
| Phase 3 | HTTP Polling Removal | **DONE** | Enrichment workers require SQS (`sys.exit(1)` without it). APScheduler removed from enrichment workers. |
| Phase 4 | Cleanup | **NOT DONE** | Feature flags remain, deprecated settings remain, stale EC2 worker configs remain |

**This audit is Phase 4.**
