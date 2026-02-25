# Next PR Checklist — Ready to Execute

**Date**: 2026-02-26
**Repo**: `dev-heimdex-for-livecommerce` (main branch)

---

## PR1: Docs + Deprecation Notices

> No code changes. No behavior changes. Safe to merge first.

- [ ] Add `docs/housekeeping/00_findings.md`
- [ ] Add `docs/housekeeping/01_cleanup_plan.md`
- [ ] Add `docs/housekeeping/02_deprecation_map.md`
- [ ] Add `docs/housekeeping/03_next_pr_checklist.md`
- [ ] Update `AGENTS.md` section "STAGING INFRASTRUCTURE" to mention:
  - Enrichment workers now on Aircloud+ GPU (not EC2)
  - drive-worker remains on EC2 for discovery
  - SQS queue URLs and Aircloud+ image references

**Verification**: No tests affected. Docs review only.

---

## PR2: Guard EC2 Enrichment Workers (prevent accidental restart)

> Critical safety PR. Prevents dual-consumer conflict.

### deploy-staging.yml changes

- [ ] Remove `WORKER_CHANGED` detection (lines 63, 69–70):
  ```diff
  -            WORKER_CHANGED=false
  ...
  -            echo "$DIFF_FILES" | grep -qE '^services/drive-(stt|ocr|caption)-worker/' && WORKER_CHANGED=true || true
  -            echo "$DIFF_FILES" | grep -qE '^(docker-compose\.yml|\.env\.example)' && API_CHANGED=true && WEB_CHANGED=true && WORKER_CHANGED=true || true
  +            echo "$DIFF_FILES" | grep -qE '^(docker-compose\.yml|\.env\.example)' && API_CHANGED=true && WEB_CHANGED=true || true
  ```

- [ ] Remove worker build/restart block (lines 114–119):
  ```diff
  -            if [ "$WORKER_CHANGED" = true ] || [ "$API_CHANGED" = true ]; then
  -              echo "--- rebuilding and restarting enrichment workers ---"
  -              docker compose build drive-stt-worker drive-ocr-worker drive-caption-worker
  -              docker compose up -d --no-deps --force-recreate drive-stt-worker drive-ocr-worker drive-caption-worker
  -              sleep 5
  -            fi
  ```

- [ ] Remove `Worker changed:` from status echo (line 77):
  ```diff
  -            echo "API changed: $API_CHANGED | Web changed: $WEB_CHANGED | Worker changed: $WORKER_CHANGED"
  +            echo "API changed: $API_CHANGED | Web changed: $WEB_CHANGED"
  ```

### heimdex-media-pipelines deploy-staging.yml

- [ ] Remove enrichment worker restart step (if present)

### docker-compose.yml profile guards

- [ ] Add `profiles: ["ec2-legacy"]` to `drive-stt-worker` service (line 386)
- [ ] Add `profiles: ["ec2-legacy"]` to `drive-ocr-worker` service (line 263)
- [ ] Add `profiles: ["ec2-legacy"]` to `drive-caption-worker` service (line 335)
- [ ] Add `profiles: ["face-dev"]` to `face-worker` service (line 195)
- [ ] Add `profiles: ["llama-caption"]` to `llama-caption-server` service (line 305)
- [ ] Add `profiles: ["local-dev"]` to `elasticmq` service (line 432)

### Verification

```bash
# Services in default profile (should NOT include enrichment workers)
docker compose config --services
# Expected: postgres, opensearch, minio, api, web, drive-worker

# Services with ec2-legacy profile (includes enrichment workers)
docker compose --profile ec2-legacy config --services
# Expected: above + drive-stt-worker, drive-ocr-worker, drive-caption-worker

# Services with local-dev profile (includes elasticmq)
docker compose --profile local-dev config --services
# Expected: default + elasticmq

# Full local dev (all profiles)
docker compose --profile ec2-legacy --profile local-dev --profile face-dev --profile llama-caption config --services
# Expected: all 12 services

# Tests still pass
make test
make build
make check-coupling
```

### Manual EC2 verification (after PR2 merges and deploys)

```bash
ssh -i ~/.ssh/heimdex-staging.pem ec2-user@3.34.75.63
cd /opt/heimdex/dev-heimdex-for-livecommerce

# Verify enrichment workers are NOT running
docker ps --format '{{.Names}}' | grep -E 'stt|ocr|caption-worker'
# Expected: no output

# Verify core services ARE running
docker ps --format '{{.Names}}' | grep -E 'api|web|postgres|opensearch|drive-worker'
# Expected: all 5 listed

# Verify API health
curl -s http://localhost:8000/health | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])"
# Expected: ok
```

---

## PR3: Remove Deprecated Env Vars + Stale Tests

> Only after PR2 is merged and verified stable on staging.

### docker-compose.yml

- [ ] Remove line 281: `- DRIVE_OCR_POLL_INTERVAL_SECONDS=${DRIVE_OCR_POLL_INTERVAL_SECONDS:-30}`
- [ ] Remove line 354: `- DRIVE_CAPTION_POLL_INTERVAL_SECONDS=${DRIVE_CAPTION_POLL_INTERVAL_SECONDS:-30}`
- [ ] Remove line 407: `- DRIVE_STT_POLL_INTERVAL_SECONDS=${DRIVE_STT_POLL_INTERVAL_SECONDS:-30}`

### GPU Dockerfiles — remove apscheduler

- [ ] `services/drive-caption-worker/Dockerfile.gpu` line 57: remove `"apscheduler>=3.10,<4"`
- [ ] `services/drive-stt-worker/Dockerfile.gpu` line 52: remove `"apscheduler>=3.10,<4"`
- [ ] `services/drive-ocr-worker/Dockerfile.gpu` line 55: remove `"apscheduler>=3.10,<4"`

### Stale tests

- [ ] `services/api/tests/test_stt_worker_config.py`: remove `test_stt_default_poll_interval`
- [ ] `services/api/tests/test_caption_enrichment.py`: remove assertion on `drive_caption_poll_interval_seconds`
- [ ] `services/api/tests/test_ocr_worker_job_claiming.py`: remove `test_ocr_default_poll_interval`

### config.env sync

- [ ] `infra/deploy/heimdex-staging/config.env`: set `SQS_CONSUMER_ENABLED=true`
- [ ] `infra/deploy/heimdex-staging/config.env`: change `MINIO_ENDPOINT=none` → `MINIO_ENDPOINT=`
- [ ] `infra/deploy/heimdex-staging/config.env`: add `S3_REGION=ap-northeast-2` if missing

### Verification

```bash
# No references to deprecated poll intervals in compose
grep -c 'POLL_INTERVAL' docker-compose.yml
# Expected: 1 (only DRIVE_WORKER_POLL_INTERVAL_SECONDS)

# Tests pass
make test

# GPU images build without apscheduler
# (verified by build-gpu-images.yml on next push)
```

---

## PR4: Dead Code Removal (after PR3 stable for 3+ days)

> Final cleanup. Only proceed after confirming Aircloud+ workers are stable.

- [ ] Remove deprecated poll interval fields from `worker_sdk/settings.py` (lines 57, 69, 75)
- [ ] Remove deprecated poll interval fields from `api/config.py` (lines 136, 146, 152)
- [ ] Remove `# SQS consumer configuration (Phase 2)` comments from docker-compose.yml (they're no longer "Phase 2")
- [ ] Update `docs/queue_arch/06_migration_plan.md` to mark Phase 4 as DONE
- [ ] Consider: remove MinIO from default profile if C1 investigation confirms it's unused

### Verification

```bash
make test
make build
make check-coupling

# Staging health after deploy
curl -sf https://devorg.app.heimdexdemo.dev/api/health
# Expected: {"status": "ok", ...}
```

---

## Quick Reference: What Changes Where

| File | PR1 | PR2 | PR3 | PR4 |
|------|-----|-----|-----|-----|
| `docs/housekeeping/*` | ✅ add | | | |
| `AGENTS.md` | ✅ update | | | |
| `.github/workflows/deploy-staging.yml` | | ✅ edit | | |
| `pipelines/.github/workflows/deploy-staging.yml` | | ✅ edit | | |
| `docker-compose.yml` | | ✅ profiles | ✅ rm env | ✅ rm comments |
| `Dockerfile.gpu` (×3) | | | ✅ rm apscheduler | |
| `api/tests/*` (×3) | | | ✅ rm tests | |
| `config.env` | | | ✅ sync | |
| `worker_sdk/settings.py` | | | | ✅ rm fields |
| `api/config.py` | | | | ✅ rm fields |
| `docs/queue_arch/06_migration_plan.md` | | | | ✅ update |
