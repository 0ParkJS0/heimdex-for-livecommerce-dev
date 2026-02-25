# Deprecation Map — EC2 CPU Workers → Aircloud+ GPU Workers

**Date**: 2026-02-26
**Context**: SQS Migration Phase 4 cleanup.

---

## Overview

This document maps every old EC2/CPU worker path to its Aircloud+ SQS GPU replacement.

```
BEFORE (Phase 0–2):                    AFTER (Phase 3+):
┌──────────────┐                       ┌──────────────────┐
│ EC2 Staging  │                       │ EC2 Staging      │
│              │                       │ (control plane)  │
│ API ─publish→ SQS                    │ API ─publish→ SQS│
│              │                       │ drive-worker     │
│ STT worker ──┤ consume               │   (discovery +   │
│ OCR worker ──┤ SQS                   │    processing)   │
│ Caption wkr ─┤                       └──────────────────┘
│ drive-worker │                              │
│ face-worker  │                              │ SQS
│ llama-server │                              ▼
└──────────────┘                       ┌──────────────────┐
                                       │ Aircloud+ GPU    │
                                       │                  │
                                       │ STT worker (cuda)│
                                       │ OCR worker (GPU) │
                                       │ Caption wkr (GPU)│
                                       └──────────────────┘
```

---

## Worker Path Mapping

### Caption Enrichment

| Aspect | Old (EC2 CPU) | New (Aircloud+ GPU) |
|--------|--------------|---------------------|
| **Image** | `dev-heimdex-for-livecommerce-drive-caption-worker:latest` (built on EC2) | `ghcr.io/jlee-heimdex/heimdex-caption-worker-gpu:latest` |
| **Dockerfile** | `services/drive-caption-worker/Dockerfile` (python:3.11-slim) | `services/drive-caption-worker/Dockerfile.gpu` (nvidia/cuda:12.1.1) |
| **Base image** | python:3.11-slim | nvidia/cuda:12.1.1-runtime-ubuntu22.04 |
| **Engine** | `CAPTION_ENGINE=llama_http` (llama.cpp sidecar) | `CAPTION_ENGINE=qwen2vl` (native Qwen2-VL) |
| **Model** | `OpenGVLab/InternVL2-1B` (1.88GB, CPU) | `Qwen/Qwen2-VL-2B-Instruct` (GPU-accelerated) |
| **Job source** | SQS `heimdex-caption-queue` | SQS `heimdex-caption-queue` (same queue) |
| **API access** | `http://api:8000` (docker network) | `https://devorg.app.heimdexdemo.dev` (public URL) |
| **AWS auth** | IAM Role `heimdex-staging-ec2` | Explicit keys `AKIA26IUJPAM...` |
| **GPU** | `USE_GPU=false` | `USE_GPU=true` |
| **Memory** | 4GB (docker limit) | Aircloud+ managed |
| **Sidecar** | Requires `llama-caption-server` | None (self-contained) |

### STT Enrichment

| Aspect | Old (EC2 CPU) | New (Aircloud+ GPU) |
|--------|--------------|---------------------|
| **Image** | `dev-heimdex-for-livecommerce-drive-stt-worker:latest` | `ghcr.io/jlee-heimdex/heimdex-stt-worker-gpu:latest` |
| **Dockerfile** | `services/drive-stt-worker/Dockerfile` | `services/drive-stt-worker/Dockerfile.gpu` |
| **Base image** | python:3.11-slim | nvidia/cuda:12.1.1-runtime-ubuntu22.04 |
| **Model** | `DRIVE_STT_MODEL=small` (CPU-constrained) | `DRIVE_STT_MODEL=turbo` (GPU-enabled) |
| **Device** | `STT_DEVICE=cpu` (default) | `STT_DEVICE=cuda` |
| **Precision** | `STT_COMPUTE_TYPE=int8` (default) | `STT_COMPUTE_TYPE=float16` |
| **Job source** | SQS `heimdex-stt-queue` | SQS `heimdex-stt-queue` (same queue) |
| **API access** | `http://api:8000` | `https://devorg.app.heimdexdemo.dev` |
| **GPU** | `USE_GPU=false` | `USE_GPU=true` |

### OCR Enrichment

| Aspect | Old (EC2 CPU) | New (Aircloud+ GPU) |
|--------|--------------|---------------------|
| **Image** | `dev-heimdex-for-livecommerce-drive-ocr-worker:latest` | `ghcr.io/jlee-heimdex/heimdex-ocr-worker-gpu:latest` |
| **Dockerfile** | `services/drive-ocr-worker/Dockerfile` | `services/drive-ocr-worker/Dockerfile.gpu` |
| **Base image** | python:3.11-slim | nvidia/cuda:12.6.3-runtime-ubuntu22.04 |
| **OCR engine** | `paddleocr>=2.8.0` + `paddlepaddle>=2.6.1` (CPU) | `paddlepaddle-gpu==3.3.0` (CUDA 12.6) |
| **Job source** | SQS `heimdex-ocr-queue` | SQS `heimdex-ocr-queue` (same queue) |
| **API access** | `http://api:8000` | `https://devorg.app.heimdexdemo.dev` |
| **GPU** | `USE_GPU=false` | `USE_GPU=true` |

### Drive Processing (NOT migrated)

| Aspect | EC2 (current) | Aircloud+ |
|--------|--------------|-----------|
| **Status** | **Active on EC2** | **Not on Aircloud+** |
| **Image** | `dev-heimdex-for-livecommerce-drive-worker:latest` | N/A |
| **Roles** | Discovery polling (APScheduler) + SQS processing consumer | N/A |
| **Job source** | SQS `heimdex-processing-queue` + HTTP poll for discovery | N/A |
| **Note** | Drive-worker stays on EC2. It needs docker network access to API and Google Drive OAuth state. | No Dockerfile.gpu exists. |

### Face Worker (DEAD)

| Aspect | Value |
|--------|-------|
| **Status** | Dead code. `command: sleep infinity`. |
| **Last active** | Unknown (predates SQS migration) |
| **Replacement** | None (feature deferred) |
| **Action** | Move behind `profiles: ["face-dev"]` |

### Llama Caption Server (REPLACED)

| Aspect | Value |
|--------|-------|
| **Status** | Running on EC2 but unused by Aircloud+ |
| **Replacement** | `CAPTION_ENGINE=qwen2vl` on Aircloud+ (self-contained, no sidecar) |
| **Action** | Move behind `profiles: ["llama-caption"]`, stop on EC2 |

---

## Environment Variable Deprecation

### Remove from docker-compose.yml (enrichment worker services only)

| Variable | Reason | Replacement |
|----------|--------|-------------|
| `DRIVE_OCR_POLL_INTERVAL_SECONDS` | Deprecated Phase 3. OCR worker is SQS-only. | None needed. |
| `DRIVE_CAPTION_POLL_INTERVAL_SECONDS` | Deprecated Phase 3. Caption worker is SQS-only. | None needed. |
| `DRIVE_STT_POLL_INTERVAL_SECONDS` | Deprecated Phase 3. STT worker is SQS-only. | None needed. |

### Keep (still used)

| Variable | Used by | Notes |
|----------|---------|-------|
| `DRIVE_WORKER_POLL_INTERVAL_SECONDS` | drive-worker | Discovery polling interval. Not deprecated. |
| `SQS_ENABLED` | API | Controls SQS publishing. Keep for now (Phase 4 says remove, but affects local dev). |
| `SQS_CONSUMER_ENABLED` | All workers | Controls SQS consumption. Keep for now (same reason). |
| All `SQS_*_QUEUE_URL` vars | API + workers | Active SQS queue URLs. Must keep. |

### Update in config.env (repo template)

| Variable | Current | Should be | Reason |
|----------|---------|-----------|--------|
| `SQS_CONSUMER_ENABLED` | `false` | `true` | Matches EC2 reality. Workers require it. |
| `MINIO_ENDPOINT` | `none` | `` (empty) | Match EC2. Both mean "use real S3". |
| Add `S3_REGION` | missing | `ap-northeast-2` | Present on EC2, missing from template. |

---

## CI/CD Path Mapping

### Image Build

| Old | New |
|-----|-----|
| `deploy-staging.yml` builds CPU images on EC2 via `docker compose build` | `build-gpu-images.yml` builds GPU images on GitHub Actions, pushes to GHCR |
| Images live only on EC2 | Images in `ghcr.io/jlee-heimdex/heimdex-{caption,stt,ocr}-worker-gpu` |

### Deployment

| Old | New |
|-----|-----|
| `deploy-staging.yml` → SSH → `docker compose up -d` on EC2 | Aircloud+ pulls `:latest` from GHCR (managed by Aircloud+ platform) |
| `pipelines/deploy-staging.yml` → SSH → restart workers | GPU images bake pipelines at build time (no mount needed) |

### Enrichment Worker Lifecycle

| Old | New |
|-----|-----|
| Code push → GHA SSH → EC2 docker compose build → restart | Code push → GHA docker build → GHCR push → Aircloud+ pulls latest |
| Pipelines push → GHA SSH → EC2 restart workers | Pipelines included in GPU image at build time |

---

## Source of Truth After Cleanup

| Component | Source of Truth | Location |
|-----------|----------------|----------|
| Enrichment worker code | Git repo `main` branch | `services/drive-{caption,stt,ocr}-worker/` |
| GPU worker images | GHCR | `ghcr.io/jlee-heimdex/heimdex-*-worker-gpu:latest` |
| Worker SDK | Git repo | `services/worker_sdk/` |
| SQS queue config | AWS Console / Terraform (future) | `ap-northeast-2`, account `752198711321` |
| Aircloud+ env config | Aircloud+ dashboard | Not in git (secrets) |
| EC2 staging env | `/opt/heimdex/.env` on EC2 | Synced from `infra/deploy/heimdex-staging/config.env` |
| API config | `services/api/app/config.py` | Pydantic Settings |
| Worker config | `services/worker_sdk/src/heimdex_worker_sdk/settings.py` | Pydantic Settings |
