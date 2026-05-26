# shorts-auto product v2 — golden eval set

Hand-curated ground truth for the product-anchored shorts pipeline.
The eval harness at `services/api/scripts/eval_shorts_auto_product.py`
consumes these to gate prompt and threshold changes. It is **unified**
across enumeration sources — the vision pass and the overlay pass write
the same `product_catalog_entries` rows (distinguished by
`enumeration_source`), so one harness grades both. Use `--source` to
score the vision-only, overlay-only, or unified catalog.

> Goldens are **devorg-curated on staging**, not synthetic. Curating
> against real Korean live-commerce content is the whole point —
> synthetic goldens would not catch the failure modes the hard-gates
> in `.claude/plans/shorts-auto-product-v2.md` §14 are designed to
> surface.

## When to run the eval

The eval is **not** in CI — it spends real OpenAI + Aircloud GPU
budget. It runs on demand, gated by:

1. Any bump of `EnumerationPrompt.VERSION` in `heimdex-media-contracts`
   (per plan §9 rule 5; whoever bumps owns the run).
2. Any change to `enumeration_version` or `tracker_version` constants
   in `heimdex_media_pipelines.product_enum` /
   `heimdex_media_pipelines.product_track`.
3. The Phase 2 → Phase 3 calibration gate before the prod rollout
   flag `auto_shorts_product_v2_enabled` is allowed to flip on prod
   (plan §11 phase table; §14 risks: SigLIP2 used off-label).
4. The overlay-enumeration rollout gate — before flipping the overlay
   flag on prod, the `overlay/` goldens must meet the recall/precision
   floors with `--source overlay`
   (plan `.claude/plans/overlay-enumeration-worker-migration-2026-05-25.md` S6).

## Running the harness

The CLI `services/api/scripts/eval_shorts_auto_product.py` exists and is
run inside the api container:

```bash
docker compose exec -T api python -m scripts.eval_shorts_auto_product \
    --org-slug devorg \
    --golden-dir tests/shorts_auto_product/eval/goldens \
    --source all \
    [--video-id gd_abc ... ] \
    [--label-match-threshold 0.5] \
    [--out /tmp/enum_eval.json] \
    [--allow-version-drift]
```

- `--source {vision,overlay,all}` filters the catalog query on
  `enumeration_source`. `all` (default) grades the unified catalog;
  `overlay` grades only overlay-source rows against the `overlay/`
  goldens; `vision` grades only vision-source rows.
- The harness **refuses to run** (exit 2) if a golden's declared
  `enumeration_(prompt_)version` disagrees with the versions stamped on
  the live catalog rows, unless `--allow-version-drift` is passed.
- Exit codes: `0` = all gates passed, `1` = a gate failed (apply the
  documented fallback below), `2` = runner error / version drift / no
  goldens matched.

The PURE scoring math lives in
`app.modules.shorts_auto_product.eval.enumeration_score` (stdlib only,
unit-tested in `tests/test_eval_shorts_auto_product.py` — that test is in
CI; the CLI itself is NOT, because it spends real budget). The label
matcher is pluggable: the default is deterministic token-Jaccard (no
embedder); the embedding-cosine matcher described under "Eval metrics
computed" can be injected later.

## Calibration thresholds (gate prod rollout)

Per the plan's hard-gate decisions:

| Metric                    | Floor      | Failure action                          | Scorer module |
|---------------------------|------------|-----------------------------------------|---------------|
| Enumeration recall        | ≥ 0.85     | Swap SigLIP2 → DINOv2 before prod       | `enumeration_score` |
| Enumeration precision     | ≥ 0.80     | Fall back to gpt-4o (from gpt-4o-mini)  | `enumeration_score` |
| Mean window IoU per prod  | ≥ 0.60     | Swap SigLIP2 → DINOv2 before prod       | `window_score` |

Failing any of these does **not** mean delaying — it means flipping
to the documented fallback configuration before flipping the flag.

## Coverage targets (v1)

Three livecommerce categories — the platform's biggest by volume.
Aim for 3-5 goldens per category at v1; expand reactively when
soak surfaces category-specific complaints.

| Category    | Folder         | v1 target |
|-------------|----------------|-----------|
| Cosmetics   | `cosmetics/`   | 5 videos  |
| Fashion     | `fashion/`     | 3 videos  |
| Food        | `food/`        | 3 videos  |
| Overlay     | `overlay/`     | 3-5 videos |

## Overlay source

The `overlay/` folder grades the **overlay enumeration pass** — products
named on **on-screen info cards** (price cards, spec panels, name banners
baked into the broadcast graphics), as opposed to products merely held up
in-frame (the vision pass). Both passes write the same
`product_catalog_entries` rows with a distinct `enumeration_source`
(`vision` vs `overlay`); the consolidate hook merges cross-source dupes.

Author overlay goldens against videos with rich on-screen graphics
(prefer livecommerce broadcasts that overlay product names + prices).
`expected_products` is the set of products the overlay graphics name;
`expected_negatives` is decorative chrome / sponsor banners / host
accessories the overlay detector must NOT promote to the catalog. The
schema is identical to the other categories — set `"category": "overlay"`.
A filled example lives at `overlay/_TEMPLATE.json` (files starting with
`_` are skipped by the harness; rename to `{org_slug}_{video_id}.json`).

## Golden file schema

One JSON file per video. Filename: `{org_slug}_{video_id}.json`.

```jsonc
{
  "$schema_version": "1",
  "video_id": "gd_1ABcDef...",
  "org_slug": "devorg",
  "category": "cosmetics",
  "authored_at": "2026-05-15T10:00:00Z",
  "authored_by": "user@heimdex.dev",

  // Versions this golden was authored against. The eval harness must
  // refuse to run if the live versions disagree without an explicit
  // --allow-version-drift flag.
  "enumeration_prompt_version": "v1.0",
  "enumeration_version": "v1.0",
  "tracker_version": "v1.0",

  // Ground truth — list every product the host actively presents.
  // Indirect mentions, sponsor banners, and host accessories MUST
  // NOT appear here (they're the negative examples the enumerator
  // is being graded on excluding).
  "expected_products": [
    {
      "label_kr": "핑크 세럼 병",
      "label_en_hint": "pink rectangular serum bottle",
      "first_appearance_ms": 14200,
      "expected_appearance_count_min": 4,
      "expected_total_seconds_min": 28,
      "category_hint": "skincare",

      // expected_windows_ms — pre-merged half-open [start_ms, end_ms)
      // spans of every annotator-marked window where this product was
      // either on screen (overlay row) or being spoken about (mention
      // row). The OVERLAY-only golden carries only overlay rows; the
      // category-folder golden carries the merged union of both
      // sources. Feeds the scene-selection scorer at
      // app.modules.shorts_auto_product.eval.window_score; the picker
      // is graded on how well its selected scene windows overlap this
      // set (coverage recall + selection precision + IoU).
      "expected_windows_ms": [
        [14200, 28800],
        [74100, 91500],
        [138600, 156800]
      ]
    }
  ],

  // For each expected product, the ideal final-clip windows the
  // pipeline should select within a 60s preset. Window IoU is
  // computed against this set per duration_preset.
  "expected_clip_for_product": [
    {
      "label_kr": "핑크 세럼 병",
      "duration_preset_sec": 60,
      "ideal_window_set": [
        { "scene_id": "gd_1A_scene_007", "start_ms":  18400, "end_ms":  29200 },
        { "scene_id": "gd_1A_scene_012", "start_ms":  74100, "end_ms":  91500 },
        { "scene_id": "gd_1A_scene_018", "start_ms": 138600, "end_ms": 156800 }
      ]
    }
  ],

  // Optional: explicit negative examples to score precision. Items
  // here SHOULD NOT appear in the catalog. Helps catch host-accessory
  // and background-prop pollution.
  "expected_negatives": [
    "host's gold watch",
    "sponsor mug on desk",
    "studio ring light"
  ]
}
```

## Authoring workflow (devorg, on staging)

1. Pick a representative video on `devorg.app.heimdexdemo.dev` covering
   the target category. Prefer 30-60 minute videos with 3-8 distinct
   products and at least one obvious host-accessory negative example.
2. Watch the video and fill `expected_products` + `expected_negatives`
   with the source-of-truth list. Do **not** look at any pipeline
   output yet — bias the LLM by inspecting its output and you've
   ruined the golden.
3. For each expected product, scrub the timeline and capture the
   ideal `ideal_window_set` for the 60s preset. Optional: add 30s
   and 90s presets if the video supports it.
4. Commit the JSON file under the appropriate category folder.
5. Run the eval harness against the new golden + the existing set
   to confirm metrics still pass before merging.

## Eval metrics computed

The two scorer modules grade complementary halves of the pipeline:

### Enumeration (catalog correctness — `enumeration_score.py`)

- **Enumeration recall**: proportion of `expected_products` surfaced
  in the catalog (label match via cosine sim of LLM-label embeddings,
  threshold 0.65 — matches the spec authoring-vs-runtime label drift).
- **Enumeration precision**: 1 − (count of catalog entries matching
  any `expected_negatives` label / total catalog entries).

### Scene selection (windows correctness — `window_score.py`)

For each `(video, product)` pair the scorer compares the picker's
selected scene windows against `expected_windows_ms` (every annotator-
marked window where the product was on screen OR being spoken about):

- **Coverage recall** = `|expected ∩ actual| / |expected|` — did the
  picker cover the time the product was actually featured?
- **Selection precision** = `|expected ∩ actual| / |actual|` — of the
  time the picker output, how much was product-relevant?
- **Window IoU** = `|∩| / |∪|` — composite (Jaccard on time).

The README floor (mean window IoU ≥ 0.60) is the calibration gate;
coverage_recall and selection_precision are surfaced as breakdown
metrics so a failing IoU can be diagnosed without rerunning.

The scorer treats `expected_windows_ms` as PRE-MERGED half-open
millisecond intervals (the converter merges overlay + mention rows
for the same product so overlap doesn't double-count). Products with
zero ground-truth time are excluded from the per-video mean — see
`window_score.score_video` for the aggregation rules.

A separate window-IoU metric for **final-clip** windows (i.e. the
operator's chosen 30/60/90s short slice) will use the
`expected_clip_for_product[].ideal_window_set` field when Phase B
annotation lands. That's distinct from `expected_windows_ms` (which
is the every-where-the-product-appeared ground truth, not the ideal-
final-clip pick).

A run is a **pass** if all gates in the calibration table above meet
their floors. Any failure flags the run output for review and prevents
the tracker_version / prompt_version bump from shipping.

## Storage rules

- Goldens are checked into the repo (this directory).
- The video files themselves are **not** checked in — they live in
  the org's S3 bucket. The eval harness pulls them via the same
  `drive_files` lookup the API uses.
- Never check in screenshots or crops from the source video.
  Goldens describe expectations; they don't carry pixel data.
