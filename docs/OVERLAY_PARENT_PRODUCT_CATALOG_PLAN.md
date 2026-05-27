# Overlay-Parent Product Catalog Plan

Updated: 2026-05-27

## Context

The auto-shorts product wizard currently shows products from
`GET /api/shorts/auto/products/{video_id}` as soon as that endpoint returns a
non-empty catalog. That catalog is backed by `product_catalog_entries`.

Today the list can change across refreshes because the first non-empty catalog
does not mean the backend is done:

1. The product-select UI triggers `POST /api/shorts/auto/products/{video_id}/scan`.
2. The product-enumerate worker persists rows through
   `/internal/products/{job_id}/complete`.
3. The API may then schedule STT enumeration augmentation.
4. The API may also schedule catalog consolidation.
5. `GET /products` currently returns all active rows and the frontend treats the
   first non-empty response as selectable.

This creates two user-visible problems:

- Product cards from multiple enumeration variants can appear together.
- Refreshes can show different products or ordering while STT/consolidation is
  still mutating the catalog.

For livecommerce videos, overlay enumeration has produced the best product
cards. The desired product policy is therefore:

```text
Visible product cards:
  overlay rows only, when overlay rows exist

Fallback:
  consolidated non-overlay rows only when overlay finds zero products

STT:
  alias/label/mention enrichment only, not a competing visible card source

Vision:
  disabled for product-card enumeration in overlay-parent mode
```

## Current Relevant Code

- Public product endpoints:
  `services/api/app/modules/shorts_auto_product/router.py`
- Product scan orchestration:
  `services/api/app/modules/shorts_auto_product/service.py`
- Product catalog reads/writes:
  `services/api/app/modules/shorts_auto_product/repositories/catalog.py`
- Worker callback:
  `services/api/app/modules/shorts_auto_product/internal_router.py`
- Catalog consolidation:
  `services/api/app/modules/shorts_auto_product/consolidate/`
- STT enumeration augmentation:
  `services/api/app/modules/shorts_auto_product/enumerate_stt/`
- Product-enumerate worker:
  `services/product-enumerate-worker/src/tasks/enumerate.py`
- Wizard product panel:
  `services/web/src/features/shorts-auto-product-wizard/components/InlineWizardProductPanel.tsx`
- Frontend API client:
  `services/web/src/lib/api/shorts-auto-product-wizard.ts`

The worker already supports these modes:

```text
vision          -> legacy visual product pass
vision+overlay  -> visual pass plus overlay pass
overlay         -> overlay pass only
```

Before this work, the API chose only `vision` or `vision+overlay`.
Overlay-parent mode should allow the API to choose `overlay`.

## Goals

1. Make overlay the primary product catalog source for the wizard.
2. Prevent non-overlay variants from showing as competing product cards when
   overlay rows exist.
3. Make the frontend wait until the backend has finished all enabled
   catalog-finalization work.
4. Keep API, worker, STT augmentation, consolidation, and frontend loosely
   coupled.
5. Add deterministic ordering so refreshes return the same product list.
6. Test source priority, readiness behavior, fallback behavior, and UI polling.

## Non-Goals

- Do not remove legacy vision enumeration yet.
- Do not remove STT enumeration code yet.
- Do not rewrite tracking or rendering.
- Do not make the frontend infer backend completeness with timers.
- Do not import worker modules into API code.

## Target Backend Behavior

### 1. Add Catalog Readiness

Add a backend-owned readiness model so `scan_status="complete"` is no longer
overloaded to mean "safe to show final products."

Preferred shape: a dedicated `product_catalog_runs` table owned by
`shorts_auto_product`.

Suggested fields:

```text
id UUID primary key
org_id UUID not null
video_id UUID not null
scan_job_id UUID nullable
status text not null
source_mode text not null
overlay_policy text not null
started_at timestamptz not null
vision_completed_at timestamptz nullable
overlay_completed_at timestamptz nullable
stt_completed_at timestamptz nullable
consolidation_completed_at timestamptz nullable
finalized_at timestamptz nullable
error_code text nullable
error_message text nullable
created_at timestamptz not null
updated_at timestamptz not null
```

Suggested statuses:

```text
queued
enumerating
augmenting_stt
consolidating
ready
failed
```

Readiness must be driven by enabled backend steps:

- If STT enumeration is disabled, do not wait for STT.
- If consolidation is disabled, do not wait for consolidation.
- If overlay parent is enabled and overlay finds products, those rows are the
  visible catalog.
- If overlay parent is enabled and overlay finds zero products, apply the
  configured fallback policy.

### 2. Extend Product Catalog Response

Extend `ProductCatalogResponse` with finalization fields:

```python
catalog_status: Literal[
    "never",
    "enumerating",
    "augmenting_stt",
    "consolidating",
    "ready",
    "failed",
]
catalog_finalized_at: datetime | None
catalog_revision_id: UUID | None
```

Compatibility: keep existing `scan_status` during rollout. The frontend should
switch to `catalog_status`.

Response rules:

- If `catalog_status != "ready"`, return `products=[]`.
- If `catalog_status == "ready"`, return the final visible product list.
- If finalization fails, return `catalog_status="failed"` and no products
  unless we explicitly introduce degraded mode later.

### 3. Add Overlay-Parent Setting

Add:

```python
auto_shorts_product_v2_overlay_parent_enabled: bool = False
```

Update `ProductScanService._enumeration_mode()`:

```text
overlay_track_enabled=false, overlay_parent_enabled=false -> vision
overlay_track_enabled=true,  overlay_parent_enabled=false -> vision+overlay
overlay_track_enabled=true,  overlay_parent_enabled=true  -> overlay
overlay_track_enabled=false, overlay_parent_enabled=true  -> vision, with warning
```

This prevents legacy vision rows from being generated when the desired product
source is overlay.

### 4. Add Source-Aware Product Visibility

Keep the low-level repository method that returns all active rows, but add a
separate read path for user-selectable product cards.

Suggested method:

```python
list_visible_for_product_selection(
    *,
    org_id: UUID,
    video_id: UUID,
    overlay_parent_enabled: bool,
) -> list[ProductCatalogEntry]
```

Visibility policy:

1. Load active, non-rejected rows.
2. If overlay-parent mode is enabled and active overlay rows exist, return only
   overlay rows.
3. If overlay-parent mode is enabled and no overlay rows exist, return fallback
   rows only after finalization.
4. If overlay-parent mode is disabled, preserve the current all-active behavior,
   but still apply deterministic ordering.

Deterministic ordering:

```text
source_priority ASC
prominence_score DESC NULLS LAST
enumeration_confidence DESC
first_mention_ms ASC NULLS LAST
created_at ASC
id ASC
```

Suggested source priority:

```text
overlay = 0
stt = 1
vision = 2
hybrid / manifest / stt_xref = 3
```

In strict overlay-parent mode, source priority is mostly a fallback concern
because visible rows should be overlay-only when overlays exist.

### 5. Make Consolidation Overlay-Aware

Update consolidation so overlay rows are treated as product catalog evidence,
not as generic on-screen graphics.

Current prompt describes `vision` and `stt`, but overlay rows now exist. It also
has an `on_screen_graphic` rejection category, which can conflict with overlay
because overlay products intentionally come from product info graphics.

Required prompt changes:

- Inputs may include `overlay`, `vision`, and `stt`.
- Overlay rows are high-priority product catalog evidence.
- Do not reject overlay rows as `on_screen_graphic` merely because they came
  from graphics.
- For duplicate groups, prefer canonical row by source:

```text
overlay > stt > vision
```

- Canonical labels may still use STT spoken terms when they better represent
  the product, but the canonical row should remain overlay when possible so the
  card keeps the best crop/visual anchor.

Add deterministic post-LLM guard:

```python
if group contains overlay rows and canonical_entry_id is non-overlay:
    switch canonical_entry_id to best overlay row
    preserve canonical_label from LLM/STT if desired
    move old canonical id into member_entry_ids
```

This ensures overlay remains the parent even if the LLM chooses an STT or vision
row as canonical.

### 6. Finalization Orchestration

Replace ambiguous fire-and-forget readiness with explicit finalization state.

Suggested lifecycle:

1. Scan starts:
   - create `ProductScanJob`
   - create/update `ProductCatalogRun(status="queued")`

2. Worker claim:
   - mark run `enumerating`

3. Worker complete:
   - insert overlay rows
   - mark overlay/worker completion
   - if STT enabled, mark `augmenting_stt` and schedule STT
   - else if consolidation enabled, mark `consolidating` and schedule
     consolidation
   - else mark `ready`

4. STT task complete:
   - insert STT rows if enabled
   - mark STT complete
   - if consolidation enabled, mark `consolidating`
   - else mark `ready`

5. Consolidation complete:
   - apply overlay-aware merges/rejections
   - mark `ready`

6. Any terminal failure:
   - mark `failed` with reason

## Target Frontend Behavior

The frontend should stop treating a non-empty product list as completion.

Current behavior:

```ts
if (resp.products.length > 0) {
  setEntries(resp.products);
  setPollState("ready");
}
```

Target behavior:

```ts
if (resp.catalog_status === "ready") {
  setEntries(resp.products);
  setPollState(resp.products.length > 0 ? "ready" : "no_products");
  return;
}

if (resp.catalog_status === "failed") {
  setPollState("error");
  return;
}

setPollState("enumerating");
pollAgain();
```

Suggested UI status labels:

```text
enumerating     -> 상품 정보 인식 중
augmenting_stt  -> 방송 멘트 확인 중
consolidating   -> 상품 목록 정리 중
ready           -> 완료
failed          -> 상품 인식 실패
```

No frontend timeout should decide `no_products` while the backend says it is
still processing.

## Loose Coupling Requirements

- `ProductScanService` must not import worker modules.
- Worker code must not import API repositories or SQLAlchemy models.
- Worker reports through internal API callbacks only.
- STT enumeration and consolidation report completion through
  `shorts_auto_product` service/repository methods.
- Catalog visibility policy belongs in API service/repository code, not
  frontend filtering.
- Frontend consumes `catalog_status` and `products`; it should not know which
  backend tasks are enabled.
- Feature flags/settings decide pipeline composition.

## Testing Strategy

### Backend Unit Tests

`ProductScanService._enumeration_mode()`:

- overlay off -> `vision`
- overlay on, overlay parent off -> `vision+overlay`
- overlay on, overlay parent on -> `overlay`
- overlay parent on but overlay off -> fallback `vision` and log warning

Catalog visibility:

- overlay rows exist and overlay parent enabled -> returns overlay only
- overlay rows absent and overlay parent enabled -> returns fallback rows
- rejected overlay rows ignored
- deterministic ordering with equal scores
- `NULL` prominence sorts last

Consolidation:

- group with overlay + vision chooses overlay canonical
- group with overlay + STT chooses overlay canonical
- STT label/aliases may enrich overlay canonical row
- overlay row is not rejected as `on_screen_graphic`
- deterministic post-LLM guard corrects non-overlay canonical

Catalog readiness:

- scan created -> `queued`
- worker claimed -> `enumerating`
- worker complete with STT disabled and consolidation disabled -> `ready`
- worker complete with STT enabled -> `augmenting_stt`
- STT complete with consolidation enabled -> `consolidating`
- consolidation complete -> `ready`
- failure -> `failed`

`GET /products`:

- before ready returns `products=[]`
- ready returns final visible products
- failed returns no products and failed status
- existing `scan_status` remains compatible during rollout

### Worker Tests

Keep existing overlay mode tests:

- `vision+overlay` emits both sources
- `overlay` skips vision and emits overlay only
- `vision` emits vision only

Add API publish payload test:

- when overlay parent is enabled, SQS message carries
  `enumeration_mode="overlay"`

### Integration Tests

Overlay-parent scan:

1. Trigger scan.
2. Simulate worker complete with overlay rows.
3. Simulate finalization.
4. Assert API returns only overlay rows after `catalog_status="ready"`.

Overlay zero-product fallback:

1. Overlay returns zero rows.
2. If fallback enabled, return consolidated fallback rows after ready.
3. If fallback disabled, return ready with empty product list.

STT enabled:

1. Worker complete does not expose products yet.
2. STT complete still waits for consolidation if consolidation is enabled.
3. After consolidation, products appear once.

Consolidation delayed:

1. `GET /products` during delay returns `catalog_status="consolidating"` and
   `products=[]`.
2. After completion, same endpoint returns stable products.

### Frontend Tests

`InlineWizardProductPanel`:

- does not render grid when `catalog_status !== "ready"`
- renders status-specific loading copy
- renders grid when `catalog_status="ready"`
- renders no-products only when ready with empty products
- renders error only when failed

Rescan:

- clears prior entries
- waits for new `catalog_revision_id` or expected `job_id`
- does not flash previous catalog

Selection:

- selected ids come only from final ready products
- multi-select payload remains sorted

### Staging Verification

1. Pick a known livecommerce video where overlay performs best.
2. Enable:

```text
AUTO_SHORTS_PRODUCT_V2_OVERLAY_TRACK_ENABLED=true
AUTO_SHORTS_PRODUCT_V2_OVERLAY_PARENT_ENABLED=true
```

3. Trigger product scan.
4. Confirm worker logs show `enumeration_mode=overlay`.
5. Poll API manually:
   - no product cards before `catalog_status=ready`
   - final response contains only `enumeration_source="overlay"` when overlay
     rows exist
6. Refresh browser multiple times:
   - same product count
   - same order
   - same labels
7. Trigger rescan:
   - old products disappear during processing
   - new final catalog appears only after ready

## Rollout Plan

1. Add backend readiness schema and repository.
2. Add `catalog_status` response while preserving `scan_status`.
3. Add `AUTO_SHORTS_PRODUCT_V2_OVERLAY_PARENT_ENABLED`.
4. Update API enumeration mode selection.
5. Add source-aware visible catalog method.
6. Update consolidation prompt and deterministic overlay canonical guard.
7. Update frontend to wait for `catalog_status="ready"`.
8. Add unit/integration/frontend tests.
9. Enable on staging.
10. Verify repeat-refresh consistency.
11. Promote to production after staging consistency is confirmed.

## Implementation Log

### 2026-05-27

Implemented the first backend and frontend slice:

- Added `product_catalog_runs` as the durable readiness boundary for a video's
  selectable catalog. This keeps UI readiness out of frontend timers and avoids
  treating a non-empty intermediate catalog as final.
- Added `catalog_status`, `catalog_finalized_at`, and `catalog_revision_id` to
  the product catalog response while keeping legacy `scan_status` for rollout
  compatibility.
- Added `AUTO_SHORTS_PRODUCT_V2_OVERLAY_PARENT_ENABLED`.
- Updated API enumeration mode selection:
  - overlay track off -> `vision`
  - overlay track on -> `vision+overlay`
  - overlay track on plus overlay-parent on -> `overlay`
- Added source-aware product selection reads. In overlay-parent mode, active
  overlay rows are returned first and non-overlay rows are hidden when any
  overlay rows exist.
- Updated public product reads so products are returned only when
  `catalog_status="ready"`. During `enumerating`, `augmenting_stt`, or
  `consolidating`, the response has `products=[]`.
- Sequenced backend finalization so worker completion can move into STT
  augmentation, then consolidation, then ready. Consolidation completion marks
  the catalog run ready even when consolidation is a no-op.
- Updated the wizard polling path so the frontend waits for
  `catalog_status="ready"` before rendering product cards. The frontend keeps a
  backward-compatible fallback for old responses that have products but no
  `catalog_status`.
- Marked catalog runs failed when SQS publish fails after run creation, so the
  UI does not wait on a run that can never reach a worker callback.

New information found while implementing:

- The existing worker migration already put overlay enumeration inside
  `services/product-enumerate-worker` as a mode; no second worker path is needed
  for this slice.
- STT scheduling must be treated as configured only when both the STT flag and
  `OPENAI_API_KEY` are present. Otherwise the API can move a catalog run into an
  STT wait state while the scheduler intentionally does nothing.
- Some internal-router tests use synchronous `MagicMock` sessions instead of an
  async DB session. `ProductCatalogRunRepository` now tolerates awaitable and
  non-awaitable mock session methods so the tests can stay unit-level.
- Vitest v4.0.18 in this repo does not support `--runInBand`; use
  `npx vitest run ...` for focused web tests.
- The consolidation prompt had older visual-product language and
  `on_screen_graphic` rejection wording. Fixed in the next step with
  `v2.2-overlay-source-parent`.

Focused verification run on 2026-05-27:

```text
cd services/api
.venv/bin/pytest \
  tests/test_shorts_auto_product_overlay_enumeration.py \
  tests/test_shorts_auto_product_schemas.py \
  tests/test_shorts_auto_product_service.py \
  tests/test_shorts_auto_product_phase4_foundation.py \
  tests/test_shorts_auto_product_internal_by_video.py \
  -q --tb=short

Result: 83 passed, 1 existing Pydantic deprecation warning
```

```text
cd services/web
npx vitest run \
  src/features/shorts-auto-product-wizard/__tests__/InlineWizardProductPanel.test.tsx \
  src/features/shorts-auto-product-wizard/__tests__/WizardStepSelectProduct.test.tsx

Result: 23 passed; existing React act warnings remain in InlineWizardProductPanel tests
```

After adding the focused readiness/overlay tests, the final focused pass was:

```text
API: 85 passed, 1 existing Pydantic deprecation warning
Web: 23 passed; existing React act warnings remain
Web type-check: passed
```

Additional focused tests added:

- Backend hides products while a run is `consolidating`, even if catalog rows
  already exist.
- Backend calls the visible-product repository with
  `overlay_parent_enabled=True` when the catalog is ready.
- Frontend keeps showing the loading state when `catalog_status` is
  `consolidating`, even if the response includes product rows.

### 2026-05-27 Prompt Follow-Up

Resolved the overlay/source-quality conflict in consolidation:

- Bumped the consolidation prompt from `v2.1-stt-cross-reference` to
  `v2.2-overlay-source-parent` in code, config, and Docker Compose fallback.
- Updated the prompt to name `overlay` as a first-class source alongside
  `vision` and `stt`.
- Rewrote the `on_screen_graphic` rejection rule so true non-product graphics
  are still rejectable, but sellable overlay commerce graphics are not rejected
  merely because they are on-screen graphics.
- Added an explicit source-preference rule:
  - choose overlay row as `canonical_entry_id` when a merged group has a
    sellable overlay row
  - else choose vision row when present
  - else choose STT row
  - canonical label may still come from STT or `host_spoken_terms`
- Added a deterministic post-LLM guard,
  `_prefer_product_card_source_canonical`, so the DB parent row is corrected to
  overlay/vision even if the LLM chooses the STT row as canonical.

Verification:

```text
cd services/api
.venv/bin/pytest tests/test_shorts_auto_product_consolidate_prompt.py -q --tb=short

Result: 17 passed, 1 existing Pydantic deprecation warning
```

Final focused backend pass after fixing a test-isolation leak in
`test_shorts_auto_product_service.py`:

```text
cd services/api
.venv/bin/pytest \
  tests/test_shorts_auto_product_consolidate_prompt.py \
  tests/test_shorts_auto_product_overlay_enumeration.py \
  tests/test_shorts_auto_product_schemas.py \
  tests/test_shorts_auto_product_service.py \
  tests/test_shorts_auto_product_phase4_foundation.py \
  tests/test_shorts_auto_product_internal_by_video.py \
  -q --tb=short

Result: 102 passed, 1 existing Pydantic deprecation warning
```

## Open Questions

1. Should overlay-parent fallback to non-overlay rows be enabled by default when
   overlay finds zero products, or should the UI show no products?
2. Should STT rows ever be visible as standalone product cards in
   overlay-parent mode, or only as alias/label enrichment?
3. Should degraded mode expose products if consolidation fails, or should the
   UI fail closed? The current implementation fails closed.
4. Should catalog readiness be stored in a dedicated table or encoded on the
   latest enumeration job? The current implementation uses a dedicated
   `product_catalog_runs` table.
