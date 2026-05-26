# Annotator-supplied source files

The four files in this directory are the **raw exposure analysis** an
annotator filled in for each video. They are the upstream of the JSON
goldens at `../{cosmetics,fashion,food,overlay}/devorg_gd_*.json`.

| Source | Annotator | Video | Brand / Category |
|---|---|---|---|
| `AOU_gd_3e3bdad06e81ec70_제품_노출_분석.xlsx` | hj | `gd_3e3bdad06e81ec70` | AOU / cosmetics |
| `헤지스_gd_e3ea66fd1807550a_제품_노출_분석.xlsx` | hj | `gd_e3ea66fd1807550a` | Hedges / fashion |
| `(종가, 오설록) eval_overlays.csv` + `(종가, 오설록) eval_mentions.csv` | sj | `gd_d24cb28631262130` (종가) + `gd_76d7b7534ef04a00` (오설록) | Jongga + Osulloc / food |

The directory name starts with an underscore so the harness loader skips
it — the canonical inputs to the eval are the per-video JSON files, not
these files. We check the raw sheets in only for traceability when
someone later needs to audit a golden's derivation or re-run the
converter against tweaked input.

## Schema

Both xlsx files use the same two-sheet layout; both CSVs match
respectively. The columns are:

### `eval_overlays`

| column | description |
|---|---|
| `video_id` | `gd_<...>` identifier matching `drive_files.video_id` |
| `product_id` | annotator-assigned short label (`A`, `A-1`, `B`, …) |
| `product_name_ko` | full Korean product name |
| `overlay_start_hhmmss` / `overlay_end_hhmmss` | window where the overlay graphic was visible |
| `has_clear_image` / `has_title` / `has_price` | `Y`/`N` flags on what the overlay shows |
| `notes`, `filled_by` | annotator-free fields |

### `eval_mentions`

| column | description |
|---|---|
| `video_id`, `product_id`, `product_name_ko` | same as overlays |
| `mention_start_hhmmss` / `mention_end_hhmmss` | window where the product was mentioned |
| `mention_type` | one of `{spoken, both, only image}` |
| `notes`, `filled_by` | annotator-free fields |

## Corrections applied during conversion

The converter (`services/api/scripts/eval_xlsx_to_golden.py`) carries
documented data fixes for known annotator errors. Each affected golden
file lists the corrections under `_corrections_applied`. The corrections
are NOT applied to the source files in this directory — they ship as
the annotator delivered them so the original record is preserved.

See the converter docstring for the full list.

## Re-running the converter

The converter is one-shot and idempotent against these files. If new
videos arrive, append the source file here and extend `VIDEO_META` in
the converter, then re-run:

```bash
cd services/api && .venv/bin/python ../scripts/eval_xlsx_to_golden.py
# emits the JSONs to a preview dir; copy them into the right category folder
```

For one-off goldens authored from scratch (no source xlsx), follow the
authoring workflow in `../README.md` instead.
