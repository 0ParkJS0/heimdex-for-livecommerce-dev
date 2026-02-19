# Release Plan: Google Drive Sync E2E

**Date:** 2026-02-20
**Release Tag:** `gdrive-sync-v0.1.0`
**Author:** Automated release via Sisyphus

---

## Phase 0 — Current State Inventory

### 0.1 Git Status (all repos clean)

| Repo | Branch | HEAD | Clean |
|------|--------|------|-------|
| `heimdex-media-contracts` | main | `054e678` | Yes |
| `heimdex-media-pipelines` | main | `0ab3412` | Yes |
| `heimdex-agent` | main | `a6614ea` | Yes |
| `dev-heimdex-for-livecommerce` | refactor/product-scope-alignment | `009335f` | Yes |

### 0.2 Current Versions and Tags

| Repo | Current Version | Latest Tag | Tag Commit | Commits Since Tag |
|------|----------------|------------|------------|-------------------|
| contracts | 0.4.0 | v0.4.0 | `6751a27` | 2 (`SourceType` enum, `IngestSceneDocument` schemas) |
| pipelines | 0.5.0 | v0.5.0 | `7390226` | 1 (`transcoding` module) |
| agent | 0.1.0 (build-time via ldflags) | v0.5.6 | `1aaa3c0` | 1 (docs: SourceType reference) |
| SaaS (api) | 0.1.0 | (none) | N/A | Feature branch, not on main |

### 0.3 New Version Plan

| Repo | Old Version | New Version | Rationale |
|------|-------------|-------------|-----------|
| contracts | 0.4.0 | **0.5.0** | New schemas: `IngestSceneDocument`, `IngestScenesRequest`, `SourceType` |
| pipelines | 0.5.0 | **0.6.0** | New module: `transcoding` (probe + proxy transcode); pin contracts >=0.5.0 |
| agent | v0.5.6 | **v0.5.7** | Docs update referencing canonical SourceType |
| SaaS | (untagged) | **gdrive-sync-v0.1.0** | First tagged release with Google Drive Sync capability |

### 0.4 Drive Feature Flags (all default-off)

| Flag | Default | Location |
|------|---------|----------|
| `DRIVE_CONNECTOR_ENABLED` | `false` | `config.py:102` |
| `DRIVE_ENRICHMENT_ENABLED` | `false` | `config.py:120` |
| `DRIVE_OCR_ENABLED` | `false` | `config.py:123` |
| `DRIVE_STT_ENABLED` | `false` | `config.py:130` |

All verified via unit tests (`test_drive_config.py`, `test_ocr_worker_job_claiming.py`, `test_stt_worker_config.py`).

### 0.5 Production Build Mode Assessment

**Current state (dev mode):**
- All services use `pip install -e` (editable installs)
- docker-compose.yml mounts `../heimdex-media-contracts` and `../heimdex-media-pipelines` as read-only volumes
- Entrypoints run `pip install --no-deps -e /opt/heimdex-media-contracts` at container start
- API Dockerfile strips `heimdex-media-contracts` from pyproject.toml during build (line 12)

**Release mode plan:**
- Add `heimdex-media-contracts>=0.5.0` and `heimdex-media-pipelines>=0.6.0` as formal dependencies in worker `pyproject.toml` files
- Create `docker-compose.release.yml` override that removes local mounts and editable installs
- Dockerfiles gain a `RELEASE_MODE` build arg for baking dependencies at image build time
- Staging continues using current approach (EC2 has cloned repos)

### 0.6 Test Baselines

| Repo | Tests Passing | Skipped | Command |
|------|---------------|---------|---------|
| contracts | 237 | 0 | `.venv/bin/python -m pytest tests/` |
| pipelines | 225 | 10 | `.venv/bin/python -m pytest tests/` |
| agent | All (14 packages) | 0 | `go test ./...` |
| SaaS API | 682 | 10 | `.venv/bin/python -m pytest tests/` |

### 0.7 Infrastructure

| Component | Value |
|-----------|-------|
| Container Registry | `ghcr.io/heimdex` (config.env) |
| Image Tag Strategy | `IMAGE_TAG=latest` (staging) |
| Staging Deploy | SSH + git pull + `docker compose build` on EC2 |
| CI/CD (contracts) | Tag push → test → PyPI publish → GitHub Release |
| CI/CD (pipelines) | Tag push → test → build wheel → GitHub Release |
| CI/CD (agent) | Tag push → test → GoReleaser → bundle → S3 upload |
| CI/CD (SaaS) | Push main → SSH deploy → build → migrate → restart |

---

## Phase 1 — Release Contracts v0.5.0 + Pipelines v0.6.0

### 1.1 Contracts v0.5.0

**Changes since v0.4.0:**
- `feat(ingest): add SourceType canonical enum`
- `feat(ingest): add IngestSceneDocument and IngestScenesRequest schemas`

**Steps:**
1. Bump version in `pyproject.toml` to `0.5.0`
2. Commit: `chore(release): bump version to 0.5.0`
3. Run tests (237 expected)
4. Build wheel: `python -m build`
5. Push commit + tag: `git push origin main && git push origin v0.5.0`
6. CI publishes to PyPI automatically

### 1.2 Pipelines v0.6.0

**Changes since v0.5.0:**
- `feat(transcoding): add probe and proxy transcode module`

**Steps:**
1. Bump version in `pyproject.toml` to `0.6.0`
2. Update contracts dependency: `heimdex-media-contracts>=0.5.0`
3. Commit: `chore(release): bump version to 0.6.0`
4. Run tests (225 expected, 10 skipped)
5. Build wheel: `python -m build`
6. Push commit + tag: `git push origin main && git push origin v0.6.0`
7. CI builds wheel + creates GitHub Release

---

## Phase 2 — Release Agent v0.5.7

**Changes since v0.5.6:**
- `docs(cloud): reference canonical SourceType from contracts`

**Steps:**
1. Push unpushed commit: `git push origin main`
2. Tag: `git tag v0.5.7`
3. Push tag: `git push origin v0.5.7`
4. CI triggers: test → GoReleaser → bundle → S3 upload
5. Verify manifest at S3 URL updates to v0.5.7

---

## Phase 3 — SaaS Dependency Pinning + Release Config

### 3.1 Add Formal Dependencies

Update these `pyproject.toml` files to declare contracts/pipelines:

| Service | File | Add |
|---------|------|-----|
| api | `services/api/pyproject.toml` | Already has `heimdex-media-contracts` |
| drive-worker | `services/drive-worker/pyproject.toml` | `heimdex-media-contracts>=0.5.0`, `heimdex-media-pipelines>=0.6.0` |
| drive-ocr-worker | `services/drive-ocr-worker/pyproject.toml` | `heimdex-media-contracts>=0.5.0`, `heimdex-media-pipelines>=0.6.0` |
| drive-stt-worker | `services/drive-stt-worker/pyproject.toml` | `heimdex-media-contracts>=0.5.0`, `heimdex-media-pipelines>=0.6.0` |

### 3.2 Release Docker Configuration

Create `docker-compose.release.yml` override:
- Removes all `../heimdex-media-*` volume mounts
- Replaces entrypoint `pip install -e` commands with direct service start
- Uses build args for installing versioned packages during image build

### 3.3 Image Build

Build all 5 service images locally:
- `heimdex-api`
- `heimdex-web`
- `heimdex-drive-worker`
- `heimdex-drive-ocr-worker`
- `heimdex-drive-stt-worker`

Tag: `gdrive-sync-v0.1.0`

### 3.4 Push SaaS Changes

Push feature branch to origin with tag.

---

## Phase 4 — E2E Test Plan

### Environment: LOCAL (docker-compose)

### A) Baseline Tests (must not regress)

| ID | Test | Method | Pass Criteria |
|----|------|--------|---------------|
| A1 | Health check | GET /health | status=ok, environment=development |
| A2 | Dev login | POST /api/auth/dev-login | Returns access_token |
| A3 | Agent ingest | POST /api/ingest/scenes (3 scenes) | indexed_count=3 |
| A4 | Search (BM25) | POST /api/search {q, alpha=0.0} | Returns results matching ingested data |
| A5 | Search (hybrid) | POST /api/search {q, alpha=0.5} | Returns results |
| A6 | Org isolation | Search with wrong org | 0 results |
| A7 | Feature flags off | All DRIVE_* flags default off | Verified |
| A8 | Thumbnails | GET /api/thumbnails/{scene_id} | Non-5xx response |

### B) Google Drive Sync Tests

| ID | Test | Method | Pass Criteria |
|----|------|--------|---------------|
| B1 | Drive flag guard | POST /api/drive/* with flag off | 403 or 404 |
| B2 | Drive config defaults | Read all DRIVE_* settings | All defaults match spec |
| B3 | Internal ingest | POST /internal/ingest/scenes (gdrive source) | indexed_count matches |
| B4 | GDrive scene searchable | POST /api/search {q matching gdrive scene} | Returns gdrive results |
| B5 | Mixed source search | Search returns both agent + gdrive scenes | Both source_types present |
| B6 | OCR config defaults | Read DRIVE_OCR_* settings | All defaults match spec |
| B7 | STT config defaults | Read DRIVE_STT_* settings | All defaults match spec |
| B8 | Cross-org isolation | GDrive scenes not visible to other org | 0 results |

### C) Performance Sanity

| ID | Metric | Method | Threshold |
|----|--------|--------|-----------|
| C1 | Health response time | GET /health timing | < 1s |
| C2 | Ingest 3 scenes | POST /api/ingest/scenes timing | < 5s |
| C3 | Search latency | POST /api/search timing | < 2s |

---

## Phase 5 — Final Checklist

- [ ] All tags exist on origin (contracts v0.5.0, pipelines v0.6.0, agent v0.5.7, SaaS gdrive-sync-v0.1.0)
- [ ] Wheels built clean (contracts, pipelines)
- [ ] SaaS pinned dependency versions match tags
- [ ] Docker images build successfully
- [ ] E2E report committed and pushed
- [ ] No secrets committed
- [ ] Feature flags verified default-off
