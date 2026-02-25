# Cleanup Plan — Post-GPU-Migration Housekeeping

**Date**: 2026-02-26
**Prerequisite**: Read `00_findings.md` first.
**Migration context**: This is Phase 4 of the SQS migration plan (`docs/queue_arch/06_migration_plan.md`).

---

## Risk Categories

| Category | Definition | Action |
|----------|-----------|--------|
| **A: Safe delete now** | Dead code, unused scripts/configs, clearly obsolete. No references in active paths. | Delete in next PR. |
| **B: Deprecate/guard** | Still referenced but should not run. Add guards, warnings, or feature flags. Delete later. | Guard now, delete in follow-up PR. |
| **C: Investigate** | Unclear usage. Requires testing or confirmation before removal. | Investigate, then reclassify. |
| **D: Must keep** | Still needed for staging EC2, local dev, or Aircloud+. | Keep, but document. |

---

## Category A: Safe Delete Now

### A1. Remove enrichment worker build/restart from deploy-staging.yml

**File**: `.github/workflows/deploy-staging.yml` lines 114–119
```yaml
if [ "$WORKER_CHANGED" = true ] || [ "$API_CHANGED" = true ]; then
  docker compose build drive-stt-worker drive-ocr-worker drive-caption-worker
  docker compose up -d --no-deps --force-recreate drive-stt-worker drive-ocr-worker drive-caption-worker
fi
```
**Why stale**: Enrichment workers now run on Aircloud+ GPU. Rebuilding and restarting them on EC2 creates dual SQS consumers competing for messages.
**Replacement**: Aircloud+ pulls `ghcr.io/jlee-heimdex/heimdex-*-worker-gpu:latest` images built by `build-gpu-images.yml`.
**Change**: Remove the `if [ "$WORKER_CHANGED" ... ]` block. Also remove `WORKER_CHANGED` detection logic (lines 63, 69–70).
**Risk**: Low. EC2 enrichment workers are already stopped. This prevents accidental restart.
**Rollback**: `git revert` the commit.

### A2. Remove enrichment worker restart from pipelines deploy-staging.yml

**File**: `heimdex-media-pipelines/.github/workflows/deploy-staging.yml`
**Why stale**: Same reason as A1. Pipelines deploy restarts enrichment workers on EC2.
**Change**: Remove worker restart step. Keep API restart (pipelines code is still mounted into API container).
**Risk**: Low.
**Rollback**: `git revert`.

### A3. Remove `apscheduler` from GPU Dockerfile dependencies

**Files**:
- `services/drive-caption-worker/Dockerfile.gpu` line 57: `"apscheduler>=3.10,<4"`
- `services/drive-stt-worker/Dockerfile.gpu` line 52: `"apscheduler>=3.10,<4"`
- `services/drive-ocr-worker/Dockerfile.gpu` line 55: `"apscheduler>=3.10,<4"`

**Why stale**: Enrichment workers are pure SQS consumers. They do NOT use APScheduler. Only `drive-worker` uses it (and there is no `drive-worker/Dockerfile.gpu`).
**Change**: Remove `"apscheduler>=3.10,<4"` from all three GPU Dockerfiles.
**Risk**: Low. Build will be slightly faster/smaller. No runtime impact.
**Rollback**: Re-add the dependency.

### A4. Remove deprecated poll interval settings from docker-compose.yml

**File**: `docker-compose.yml`
```
Line 281: - DRIVE_OCR_POLL_INTERVAL_SECONDS=${DRIVE_OCR_POLL_INTERVAL_SECONDS:-30}
Line 354: - DRIVE_CAPTION_POLL_INTERVAL_SECONDS=${DRIVE_CAPTION_POLL_INTERVAL_SECONDS:-30}
Line 407: - DRIVE_STT_POLL_INTERVAL_SECONDS=${DRIVE_STT_POLL_INTERVAL_SECONDS:-30}
```
**Why stale**: Enrichment workers never read these. Code comments say `# DEPRECATED (Phase 3)`.
**Change**: Remove the three lines.
**Risk**: Very low. Settings are declared in `WorkerSettings` with defaults; removing the docker-compose passthrough is safe. The `WorkerSettings` declarations themselves stay (they're unused but harmless).
**Rollback**: Re-add lines.

### A5. Remove deprecated poll interval tests

**Files**:
- `services/api/tests/test_stt_worker_config.py` lines 26–28: `test_stt_default_poll_interval`
- `services/api/tests/test_caption_enrichment.py` line 13: asserts `drive_caption_poll_interval_seconds == 30`
- `services/api/tests/test_ocr_worker_job_claiming.py` lines 52–54: `test_ocr_default_poll_interval`

**Why stale**: Testing deprecated settings that enrichment workers no longer use.
**Change**: Remove the specific test functions/assertions. Keep the rest of each test file.
**Risk**: Very low. These test default values of unused fields.
**Rollback**: `git revert`.

---

## Category B: Deprecate/Guard

### B1. Stop EC2 enrichment worker containers (prevent restart)

**Target**: EC2 staging — containers `heimdex-drive-stt-worker`, `heimdex-drive-ocr-worker`, `heimdex-drive-caption-worker`

**Current state**: Already `Exited (137)`. But `docker compose up -d` (from deploy scripts) would restart them.

**Change (immediate, manual on EC2)**:
```bash
# On EC2: scale enrichment workers to 0
cd /opt/heimdex/dev-heimdex-for-livecommerce
docker compose stop drive-stt-worker drive-ocr-worker drive-caption-worker
docker compose rm -f drive-stt-worker drive-ocr-worker drive-caption-worker
```

**Change (code)**: Add `profiles: ["ec2-legacy"]` to enrichment worker services in `docker-compose.yml`. This prevents them from starting with default `docker compose up -d` unless explicitly enabled with `--profile ec2-legacy`.

**Risk**: Medium. If Aircloud+ goes down, there's no EC2 fallback for enrichment. But this is already the case (EC2 workers are stopped).
**Rollback**: Remove `profiles:` and `docker compose up -d` to restart EC2 workers.

### B2. Stop face-worker container

**Target**: `docker-compose.yml` lines 195–210 (face-worker service)

**Current state**: Command is `sleep infinity`. Container always exits. Image is 6.37GB.

**Change**: Add `profiles: ["face-dev"]` to the face-worker service. This removes it from default startup.

**Risk**: Very low. No active code path uses face-worker.
**Rollback**: Remove `profiles:`.

### B3. Stop llama-caption-server on EC2

**Target**: `docker-compose.yml` lines 305–334 (llama-caption-server service)

**Current state**: Running on EC2 (healthy, 4 days uptime). Aircloud+ caption worker uses `CAPTION_ENGINE=qwen2vl`, not `llama_http`.

**Change**: Add `profiles: ["llama-caption"]` to the service. Stop on EC2:
```bash
docker compose stop llama-caption-server
docker compose rm -f llama-caption-server
```

**Risk**: Medium. If EC2 caption worker is ever re-enabled and config still says `CAPTION_ENGINE=llama_http`, it would need this server. But that's the old path.
**Rollback**: Remove `profiles:` and restart.

### B4. Stop ElasticMQ on EC2

**Target**: `docker-compose.yml` lines 432–440 (elasticmq service)

**Current state**: Running on EC2. EC2 workers use real SQS (queue URLs point to `sqs.ap-northeast-2.amazonaws.com`). ElasticMQ is unused.

**Change**: Add `profiles: ["local-dev"]` to the elasticmq service.

**Risk**: Very low. ElasticMQ is only used for local development with `SQS_ENDPOINT_URL=http://elasticmq:9324`.
**Rollback**: Remove `profiles:`.

**NOTE**: ElasticMQ must remain in docker-compose for local dev. Only the default auto-start is being disabled.

### B5. Sync repo config.env with EC2 .env

**File**: `infra/deploy/heimdex-staging/config.env`

**Key drifts to fix**:
| Variable | Current (repo) | Should be |
|----------|---------------|-----------|
| `SQS_CONSUMER_ENABLED` | `false` | `true` |
| `MINIO_ENDPOINT` | `none` | `` (empty string, matching EC2) |
| Add `S3_REGION` | missing | `ap-northeast-2` |

**Risk**: Low. config.env is the "template" used by deploy.sh. Syncing it prevents future drift.
**Rollback**: Revert config.env.

---

## Category C: Investigate

### C1. MinIO container on EC2

**Current state**: Running (healthy, 3 days). EC2 `.env` has `MINIO_ENDPOINT=` (empty). API and workers use real S3.

**Question**: Is anything still writing to MinIO? Check API logs for MinIO-related errors.

**Proposed action**: If no traffic, add `profiles: ["local-dev"]` (same as ElasticMQ).

### C2. `SQS_ENABLED` / `SQS_CONSUMER_ENABLED` feature flags

Per Phase 4 of the migration plan, these should be removed (assume `true`). But:
- `SQS_ENABLED=false` is the default in code — changing default to `true` affects local dev
- Local dev uses ElasticMQ, which requires `SQS_ENDPOINT_URL`

**Proposed action**: Keep flags but update defaults in a later PR after local dev workflow is verified with SQS always-on.

### C3. CPU Dockerfiles — rename or document?

**Files**: `services/drive-{caption,stt,ocr}-worker/Dockerfile` (CPU variants)

These are used by `docker-compose.yml` for local dev. Aircloud+ uses `Dockerfile.gpu`. Should they be renamed to `Dockerfile.cpu` for clarity?

**Proposed action**: Rename in a follow-up PR. Not urgent — they work as-is.

### C4. drive-worker SQS + discovery dual path

`drive-worker` runs both SQS consumer (processing) and APScheduler (discovery). On EC2 it also consumes processing messages from SQS. Aircloud+ has no drive-worker.

**Question**: Should processing SQS consumption move to Aircloud+ too? This would require a `drive-worker/Dockerfile.gpu`.

**Proposed action**: Out of scope for this housekeeping. Document as future work.

---

## Category D: Must Keep

### D1. EC2 Core Services

| Service | Reason |
|---------|--------|
| `postgres` | Primary database. Aircloud+ workers depend on it via API. |
| `opensearch` | Search index. No managed alternative yet. |
| `api` | Control plane. Publishes SQS jobs, serves search, handles auth. |
| `web` | Customer-facing frontend. |
| `nginx` | TLS termination, routing, rate limiting. |
| `drive-worker` | Google Drive discovery + processing. No Aircloud+ equivalent. |

### D2. `build-gpu-images.yml` Workflow

Builds GPU worker images to GHCR on push to main. These images are what Aircloud+ runs. Must keep.

### D3. `worker-coupling-check.yml` and `search-quality.yml`

PR guardrails. Must keep.

### D4. CPU Dockerfiles for Local Dev

`Dockerfile` (CPU) in each enrichment worker is used by `docker-compose.yml` for local development. Must keep (see C3 for optional rename).

### D5. `docker-compose.override.yml`

Mounts worker_sdk source as editable for local dev. Must keep.

### D6. `docker-compose.release.yml`

Release overlay. Must keep for future production deploys.

### D7. `infra/deploy/` Scripts

EC2 provisioning, bootstrap, deploy, and verification scripts. Staging EC2 remains the control plane. Must keep.

### D8. `docs/queue_arch/` Migration Docs

Historical record of SQS migration phases. Keep for reference.

---

## PR Sequence

### PR1: Documentation + Deprecation Notices (no deletions, no behavior changes)

**Changes**:
- Create `docs/housekeeping/00_findings.md` (this audit)
- Create `docs/housekeeping/01_cleanup_plan.md` (this plan)
- Create `docs/housekeeping/02_deprecation_map.md` (path mapping)
- Add `# DEPRECATED` comments to stale config if not already present
- Update `AGENTS.md` "STAGING INFRASTRUCTURE" section to reflect Aircloud+ workers

**Verification**:
- All tests pass (no code changes)
- docs review

### PR2: Stop EC2 enrichment workers from auto-starting (guard)

**Changes**:
- `deploy-staging.yml`: Remove enrichment worker build/restart block (A1)
- `heimdex-media-pipelines/.github/workflows/deploy-staging.yml`: Remove worker restart (A2)
- `docker-compose.yml`: Add `profiles: ["ec2-legacy"]` to drive-stt-worker, drive-ocr-worker, drive-caption-worker (B1)
- `docker-compose.yml`: Add `profiles: ["face-dev"]` to face-worker (B2)
- `docker-compose.yml`: Add `profiles: ["llama-caption"]` to llama-caption-server (B3)
- `docker-compose.yml`: Add `profiles: ["local-dev"]` to elasticmq (B4)

**Verification**:
- `docker compose config --services` should list only: postgres, opensearch, minio, api, web, drive-worker
- `docker compose --profile ec2-legacy config --services` should include enrichment workers
- `docker compose --profile local-dev config --services` should include elasticmq
- deploy-staging.yml no longer references enrichment workers
- All existing tests pass

**Manual verification on EC2 after deploy**:
```bash
docker compose ps  # Should NOT show enrichment workers
docker compose --profile ec2-legacy ps  # Shows them if needed
```

### PR3: Remove deprecated env vars + stale tests

**Changes**:
- Remove `DRIVE_OCR_POLL_INTERVAL_SECONDS`, `DRIVE_CAPTION_POLL_INTERVAL_SECONDS`, `DRIVE_STT_POLL_INTERVAL_SECONDS` from docker-compose.yml (A4)
- Remove deprecated poll interval tests (A5)
- Remove `apscheduler` from GPU Dockerfiles (A3)
- Sync `config.env` with EC2 reality (B5)

**Verification**:
- All tests pass (after removing stale tests)
- `grep -r 'POLL_INTERVAL' docker-compose.yml` returns only `DRIVE_WORKER_POLL_INTERVAL_SECONDS` (the one that's still used)
- GPU image builds succeed without apscheduler

### PR4: Dead code removal (after PR2+PR3 proven stable)

**Changes**:
- Remove deprecated poll interval field declarations from `worker_sdk/settings.py` (lines 57, 69, 75)
- Remove deprecated poll interval field declarations from `api/config.py` (lines 136, 146, 152)
- Stop MinIO on EC2 if investigation (C1) confirms it's unused
- Consider stopping llama-caption-server on EC2 (B3)

**Verification**:
- All tests pass
- `lsp_diagnostics` clean on modified files
- Staging API health check passes
- Search quality tests pass

---

## Verification Gates (all PRs)

| Gate | Command | Expected |
|------|---------|----------|
| Unit tests | `make test` | Pass |
| Frontend build | `make build` | Pass |
| Coupling check | `make check-coupling` | Pass |
| LSP diagnostics | `lsp_diagnostics` on changed files | Clean |
| Docker compose smoke | `docker compose config` | Valid YAML, correct services |
| grep for old env vars | `grep -r 'DRIVE_OCR_POLL_INTERVAL' docker-compose.yml` | No matches (after PR3) |
| Staging health | `curl https://devorg.app.heimdexdemo.dev/api/health` | `{"status": "ok"}` |
| EC2 workers not running | `docker ps \| grep -E 'stt\|ocr\|caption-worker'` | No matches (after PR2) |
