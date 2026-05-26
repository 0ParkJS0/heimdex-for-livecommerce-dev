"""Convert the 4 annotator-supplied product-exposure files into eval goldens.

Inputs:
  * /Users/jangwonlee/Downloads/AOU_gd_3e3bdad06e81ec70_제품_노출_분석.xlsx
  * /Users/jangwonlee/Downloads/헤지스_gd_e3ea66fd1807550a_제품_노출_분석.xlsx
  * /Users/jangwonlee/Downloads/(종가, 오설록) eval_overlays.csv
  * /Users/jangwonlee/Downloads/(종가, 오설록) eval_mentions.csv

Outputs (one per video × view):
  * {category}/devorg_{video_id}.json   — graded against the unified catalog (`--source all`)
  * overlay/devorg_{video_id}.json      — graded against ONLY overlay-source rows (`--source overlay`)

Data corrections applied (logged into each affected golden under
``_corrections_applied``):

  C1. Osulloc video_id typo — overlays CSV uses ``gd_76d7b7534ef04a00`` but
      mentions CSV uses ``gd_76d7b7534ef04a10`` for the same video.
      Decision: trust the overlays file → unify on ``gd_76d7b7534ef04a00``.
  C2. AOU eval row 13 (index 12 in both sheets) — A-2 "매트바 2개 + 촉촉바
      2개 세트" 열한번째 노출: ``01:00:07 → 01:00:00`` (end before start).
      Decision: assume minute typo, set end to ``01:01:00`` (≈ same
      duration as the other A-2 appearances).
  C3. Hedges eval_mentions row 22 (index 21) — D "후드 숏 패딩점퍼" 첫 소개:
      ``00:26:56 → 00:25:00`` (end before start). Decision: assume minute
      typo, set end to ``00:27:00``.
  C4. AOU eval_mentions row 8 (index 7) — non-enum mention_type "선 spoken
      + 12초 후 both (2개 펜슬조합)". Split into TWO rows: spoken @
      00:41:31 + 12s, then both for the remainder.
  C5. ``Unnamed: 0`` column on xlsx eval_mentions sheets renamed to
      ``video_id``. Pure header-only fix; values are already correct.

Variant-SKU policy: per-variant. A, A-1, A-2 are treated as DISTINCT
products; the harness grades the model on whether it surfaces all
bundles (the operator picks an exact SKU when building a short).

Phase B placeholders: ``expected_clip_for_product`` and
``expected_negatives`` are left empty with a ``_todo`` flag — the eval
harness grades enumeration-recall + enumeration-precision immediately;
the window-IoU metric lights up only after a human fills the
``ideal_window_set`` per duration_preset (see goldens/README.md §3).
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

# ── inputs / outputs ────────────────────────────────────────────────────
DOWNLOADS = Path("/Users/jangwonlee/Downloads")
OUT_DIR = Path("/Users/jangwonlee/.claude/jobs/491ea239/goldens_preview")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── per-video metadata ──────────────────────────────────────────────────
VIDEO_META: dict[str, dict[str, Any]] = {
    "gd_3e3bdad06e81ec70": {
        "category": "cosmetics",
        "brand": "AOU",
        "category_hint_default": "color cosmetics",
        "src_label": "AOU.xlsx",
        "annotator": "hj",
    },
    "gd_e3ea66fd1807550a": {
        "category": "fashion",
        "brand": "헤지스",
        "category_hint_default": "outerwear",
        "src_label": "Hedges.xlsx",
        "annotator": "hj",
    },
    "gd_d24cb28631262130": {
        "category": "food",
        "brand": "종가",
        "category_hint_default": "korean side dish",
        "src_label": "(종가, 오설록).csv",
        "annotator": "sj",
    },
    "gd_76d7b7534ef04a00": {
        "category": "food",
        "brand": "오설록",
        "category_hint_default": "tea / dessert",
        "src_label": "(종가, 오설록).csv",
        "annotator": "sj",
    },
}

ENUMERATION_VERSION = "v1.0"
ENUMERATION_PROMPT_VERSION = "v1.0"
TRACKER_VERSION = "v1.0"
SCHEMA_VERSION = "1"
AUTHORED_AT = "2026-05-26T00:00:00Z"
AUTHORED_BY = "claude+ljin0906@gmail.com"

CORRECTIONS_GLOBAL = [
    "C5: xlsx mention sheets' Unnamed:0 column renamed to video_id (Excel export artifact).",
]


# ── helpers ─────────────────────────────────────────────────────────────

HHMMSS_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")


def to_seconds(s: Any) -> int | None:
    """Coerce HH:MM:SS string OR datetime.time → int seconds. None if junk."""
    if isinstance(s, _dt.time):
        return s.hour * 3600 + s.minute * 60 + s.second
    if isinstance(s, str) and HHMMSS_RE.match(s):
        h, m, sec = s.split(":")
        return int(h) * 3600 + int(m) * 60 + int(sec)
    return None


def merge_windows(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping [start, end) windows → disjoint cover."""
    if not spans:
        return []
    spans = sorted(spans)
    out = [spans[0]]
    for s, e in spans[1:]:
        ps, pe = out[-1]
        if s <= pe:
            out[-1] = (ps, max(pe, e))
        else:
            out.append((s, e))
    return out


# ── load + clean ────────────────────────────────────────────────────────

def load_aou() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    path = DOWNLOADS / "AOU_gd_3e3bdad06e81ec70_제품_노출_분석.xlsx"
    ovl = pd.read_excel(path, sheet_name="eval_overlays")
    ment = pd.read_excel(path, sheet_name="eval_mentions")
    if "Unnamed: 0" in ment.columns and "video_id" not in ment.columns:
        ment = ment.rename(columns={"Unnamed: 0": "video_id"})

    corrections: list[str] = []
    # C2: AOU row 13 (index 12) inverted timestamp
    for sheet_name, df in (("eval_overlays", ovl), ("eval_mentions", ment)):
        col_end = "overlay_end_hhmmss" if sheet_name == "eval_overlays" else "mention_end_hhmmss"
        col_start = "overlay_start_hhmmss" if sheet_name == "eval_overlays" else "mention_start_hhmmss"
        row = df.iloc[12]
        s = to_seconds(row[col_start])
        e = to_seconds(row[col_end])
        if s is not None and e is not None and e < s:
            df.at[12, col_end] = _dt.time(1, 1, 0)  # 01:01:00
            corrections.append(
                f"C2: AOU.{sheet_name} row idx=12 (A-2 11번째 노출) end "
                f"corrected {row[col_end]} → 01:01:00 (start={row[col_start]})"
            )

    # C4: AOU eval_mentions row 8 (index 7) — split free-form mention_type
    row = ment.iloc[7]
    if str(row["mention_type"]).startswith("선 spoken"):
        # The original spans 00:41:31 → 00:42:02 (31s).
        # Split: 12s spoken from start, then both for remainder.
        start_sec = to_seconds(row["mention_start_hhmmss"])
        end_sec = to_seconds(row["mention_end_hhmmss"])
        split_sec = start_sec + 12

        def _t(s):
            return _dt.time(s // 3600, (s % 3600) // 60, s % 60)

        # mutate row 7 → spoken half
        ment.at[7, "mention_type"] = "spoken"
        ment.at[7, "mention_end_hhmmss"] = _t(split_sec)
        ment.at[7, "notes"] = (
            (str(row["notes"]) if pd.notna(row["notes"]) else "")
            + " | split:spoken-half"
        ).strip(" |")
        # append new row → both half
        new = row.copy()
        new["mention_type"] = "both"
        new["mention_start_hhmmss"] = _t(split_sec)
        new["mention_end_hhmmss"] = _t(end_sec)
        new["notes"] = (
            (str(row["notes"]) if pd.notna(row["notes"]) else "")
            + " | split:both-half"
        ).strip(" |")
        ment = pd.concat([ment, pd.DataFrame([new])], ignore_index=True)
        corrections.append(
            "C4: AOU.eval_mentions row idx=7 (A-2 재언급) free-form "
            "mention_type 「선 spoken + 12초 후 both」 split into two rows: "
            "spoken@00:41:31-00:41:43 + both@00:41:43-00:42:02"
        )

    return ovl, ment, corrections


def load_hedges() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    path = DOWNLOADS / "헤지스_gd_e3ea66fd1807550a_제품_노출_분석.xlsx"
    ovl = pd.read_excel(path, sheet_name="eval_overlays")
    ment = pd.read_excel(path, sheet_name="eval_mentions")
    if "Unnamed: 0" in ment.columns and "video_id" not in ment.columns:
        ment = ment.rename(columns={"Unnamed: 0": "video_id"})

    corrections: list[str] = []
    # C3: Hedges eval_mentions row 22 (index 21) inverted timestamp
    row = ment.iloc[21]
    s = to_seconds(row["mention_start_hhmmss"])
    e = to_seconds(row["mention_end_hhmmss"])
    if s is not None and e is not None and e < s:
        ment.at[21, "mention_end_hhmmss"] = _dt.time(0, 27, 0)
        corrections.append(
            f"C3: Hedges.eval_mentions row idx=21 (D 후드 숏 패딩점퍼 첫 소개) "
            f"end corrected {row['mention_end_hhmmss']} → 00:27:00 "
            f"(start={row['mention_start_hhmmss']})"
        )
    return ovl, ment, corrections


def load_jongga_osulloc() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    ovl = pd.read_csv(DOWNLOADS / "(종가, 오설록) eval_overlays.csv")
    ment = pd.read_csv(DOWNLOADS / "(종가, 오설록) eval_mentions.csv")
    corrections: list[str] = []
    # C1: Osulloc video_id typo — unify on the overlays version (a00).
    typo_target = "gd_76d7b7534ef04a10"
    canonical = "gd_76d7b7534ef04a00"
    if typo_target in ment["video_id"].values:
        n = (ment["video_id"] == typo_target).sum()
        ment.loc[ment["video_id"] == typo_target, "video_id"] = canonical
        corrections.append(
            f"C1: Osulloc mentions video_id {typo_target} ({n} rows) "
            f"unified to {canonical} (matched overlays sheet)."
        )
    return ovl, ment, corrections


# ── per-product aggregation ─────────────────────────────────────────────

def _coerce_start_col(row: dict, kind: str) -> int | None:
    return to_seconds(row[f"{kind}_start_hhmmss"])


def _coerce_end_col(row: dict, kind: str) -> int | None:
    return to_seconds(row[f"{kind}_end_hhmmss"])


def build_video_aggregate(
    video_id: str,
    overlay_rows: pd.DataFrame,
    mention_rows: pd.DataFrame,
) -> dict[str, Any]:
    """Aggregate the per-appearance rows into one record per product_id."""
    ovl_v = overlay_rows[overlay_rows["video_id"] == video_id]
    ment_v = mention_rows[mention_rows["video_id"] == video_id]

    # collect spans per product_id, across BOTH sources
    pid_to_label: dict[str, str] = {}
    pid_to_overlay_spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    pid_to_mention_spans: dict[str, list[tuple[int, int]]] = defaultdict(list)

    for _, row in ovl_v.iterrows():
        pid = str(row["product_id"])
        s = _coerce_start_col(row, "overlay")
        e = _coerce_end_col(row, "overlay")
        if s is None or e is None or e <= s:
            continue
        pid_to_overlay_spans[pid].append((s, e))
        pid_to_label.setdefault(pid, str(row["product_name_ko"]))

    for _, row in ment_v.iterrows():
        pid = str(row["product_id"])
        s = _coerce_start_col(row, "mention")
        e = _coerce_end_col(row, "mention")
        if s is None or e is None or e <= s:
            continue
        pid_to_mention_spans[pid].append((s, e))
        pid_to_label.setdefault(pid, str(row["product_name_ko"]))

    all_pids = sorted(set(pid_to_overlay_spans) | set(pid_to_mention_spans))
    return {
        "pids": all_pids,
        "labels": pid_to_label,
        "overlay_spans": pid_to_overlay_spans,
        "mention_spans": pid_to_mention_spans,
    }


def _expected_product_entry(
    pid: str,
    label: str,
    overlay_spans: list[tuple[int, int]],
    mention_spans: list[tuple[int, int]],
    category_hint: str,
    *,
    overlay_only: bool = False,
) -> dict[str, Any] | None:
    """Build one ``expected_products`` entry.

    Returns ``None`` if ``overlay_only=True`` AND there are no overlay
    spans (i.e. mention-only products are dropped from the overlay
    golden — they're invisible to the overlay-enumeration pass).
    """
    if overlay_only and not overlay_spans:
        return None

    if overlay_only:
        spans = overlay_spans
        appearance_count = len(overlay_spans)
    else:
        spans = overlay_spans + mention_spans
        # Count overlay + mention rows as separate appearances; mostly
        # they're not exactly co-timed so this is honest.
        appearance_count = len(overlay_spans) + len(mention_spans)

    merged = merge_windows(spans)
    first_ms = min(s for s, _ in merged) * 1000 if merged else 0
    total_secs = sum(e - s for s, e in merged)

    return {
        "label_kr": label,
        "first_appearance_ms": first_ms,
        "expected_appearance_count_min": appearance_count,
        "expected_total_seconds_min": total_secs,
        "category_hint": category_hint,
        # Carry the annotator's product_id so the eval matcher can map
        # to the human-assigned label when ambiguous (e.g. A vs A-1).
        "annotator_product_id": pid,
    }


def emit_golden(
    *,
    video_id: str,
    overlay: pd.DataFrame,
    mention: pd.DataFrame,
    corrections_used: list[str],
    overlay_only: bool,
) -> dict[str, Any]:
    meta = VIDEO_META[video_id]
    agg = build_video_aggregate(video_id, overlay, mention)

    expected_products: list[dict[str, Any]] = []
    for pid in agg["pids"]:
        entry = _expected_product_entry(
            pid=pid,
            label=agg["labels"][pid],
            overlay_spans=agg["overlay_spans"].get(pid, []),
            mention_spans=agg["mention_spans"].get(pid, []),
            category_hint=meta["category_hint_default"],
            overlay_only=overlay_only,
        )
        if entry is not None:
            expected_products.append(entry)

    # Filter corrections: keep only ones touching this video's source file.
    src = meta["src_label"]
    corrections_for_this_video = [
        c for c in corrections_used
        if (
            (src == "AOU.xlsx" and c.startswith(("C2: AOU", "C4: AOU")))
            or (src == "Hedges.xlsx" and c.startswith("C3: Hedges"))
            or (src == "(종가, 오설록).csv" and c.startswith("C1:"))
        )
    ] + CORRECTIONS_GLOBAL

    category = "overlay" if overlay_only else meta["category"]

    return {
        "$schema_version": SCHEMA_VERSION,
        "_comment": (
            "Auto-derived from annotator-supplied exposure xlsx/csv on 2026-05-26. "
            "Source: {src} (annotator: {who}). expected_clip_for_product + "
            "expected_negatives are EMPTY — they need a Phase-B human pass "
            "(scrub the video, mark ideal 30/60/90s windows + host-accessory "
            "negatives). The enumeration-recall and enumeration-precision "
            "gates work without Phase B; the Window-IoU gate is OFF until "
            "Phase B lands."
        ).format(src=src, who=meta["annotator"]),
        "video_id": video_id,
        "org_slug": "devorg",
        "category": category,
        "authored_at": AUTHORED_AT,
        "authored_by": AUTHORED_BY,
        "enumeration_prompt_version": ENUMERATION_PROMPT_VERSION,
        "enumeration_version": ENUMERATION_VERSION,
        "tracker_version": TRACKER_VERSION,
        "_corrections_applied": corrections_for_this_video,
        "_todo_phase_b": [
            "Fill expected_clip_for_product with ideal_window_set per duration_preset (30s, 60s, 90s).",
            "Fill expected_negatives with host accessories / sponsor banners that must NOT enumerate.",
        ],
        "expected_products": expected_products,
        "expected_clip_for_product": [],
        "expected_negatives": [],
    }


def main() -> None:
    aou_ovl, aou_ment, aou_corr = load_aou()
    hed_ovl, hed_ment, hed_corr = load_hedges()
    jo_ovl, jo_ment, jo_corr = load_jongga_osulloc()

    all_corr = aou_corr + hed_corr + jo_corr
    print("Corrections applied:")
    for c in all_corr:
        print(f"  - {c}")
    print()

    # Concatenate per-source frames into one overlay + one mention df
    # so the aggregator can be agnostic to source.
    overlay = pd.concat([aou_ovl, hed_ovl, jo_ovl], ignore_index=True)
    mention = pd.concat([aou_ment, hed_ment, jo_ment], ignore_index=True)

    for video_id, meta in VIDEO_META.items():
        category = meta["category"]
        # Category-folder golden (graded against unified catalog)
        gold_cat = emit_golden(
            video_id=video_id, overlay=overlay, mention=mention,
            corrections_used=all_corr, overlay_only=False,
        )
        cat_dir = OUT_DIR / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        cat_path = cat_dir / f"devorg_{video_id}.json"
        cat_path.write_text(
            json.dumps(gold_cat, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Overlay-folder golden (graded against --source overlay)
        gold_ovl = emit_golden(
            video_id=video_id, overlay=overlay, mention=mention,
            corrections_used=all_corr, overlay_only=True,
        )
        ovl_dir = OUT_DIR / "overlay"
        ovl_dir.mkdir(parents=True, exist_ok=True)
        ovl_path = ovl_dir / f"devorg_{video_id}.json"
        ovl_path.write_text(
            json.dumps(gold_ovl, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(
            f"[{meta['brand']:8s}] {video_id} → "
            f"{category}/  ({len(gold_cat['expected_products'])} products) + "
            f"overlay/ ({len(gold_ovl['expected_products'])} products)"
        )

    print(f"\nOutput: {OUT_DIR}")


if __name__ == "__main__":
    main()
