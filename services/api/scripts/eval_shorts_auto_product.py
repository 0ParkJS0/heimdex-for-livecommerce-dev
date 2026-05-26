"""Evaluation harness for product enumeration (vision + overlay).

Scores a video's active ``product_catalog_entries`` against hand-curated
goldens and applies the calibration gates (enumeration recall ≥ 0.85,
precision ≥ 0.80) documented in
``tests/shorts_auto_product/eval/goldens/README.md``.

UNIFIED for both enumeration sources: the vision pass and the overlay
pass write the SAME ``product_catalog_entries`` rows, distinguished only
by ``enumeration_source`` (``vision`` / ``overlay`` / ``stt`` / …). This
harness filters the catalog query on ``--source`` and grades whatever
label set comes back, so the same golden can grade the vision-only,
overlay-only, or unified catalog.

Manual / on-demand only — NOT in CI. It reads the real staging catalog
(curated against real Korean live-commerce content). The PURE scoring
math lives in ``app.modules.shorts_auto_product.eval.enumeration_score``
(stdlib only, unit-tested in ``tests/test_eval_shorts_auto_product.py``);
this script is just the DB plumbing + argparse + report. Mirrors
``eval_ocr_rerank.py`` / ``eval_storyboard.py``.

Runs INSIDE the api container (needs Postgres access via the existing
``app.*`` code paths).

Usage::

    # On staging:
    ssh -i ~/.ssh/heimdex-staging.pem ec2-user@3.34.75.63
    cd /opt/heimdex/dev-heimdex-for-livecommerce
    docker compose exec -T api python -m scripts.eval_shorts_auto_product \\
        --org-slug devorg \\
        --golden-dir tests/shorts_auto_product/eval/goldens \\
        --source all \\
        [--label-match-threshold 0.5] \\
        [--out /tmp/enum_eval.json] \\
        [--allow-version-drift]

    # Or grade specific videos / a single source:
    docker compose exec -T api python -m scripts.eval_shorts_auto_product \\
        --org-slug devorg --video-id gd_abc --video-id gd_def \\
        --source overlay

Exit codes:
    0 — eval ran AND all gates passed
    1 — eval ran but a gate FAILED (apply the documented fallback)
    2 — runner error (DB unreachable, version drift without override,
        no goldens matched, bad args)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import text

# PURE scorer (stdlib only — the scoring math). All DB/IO lives in this
# script; the scorer never imports app.* / sqlalchemy.
from app.db.base import get_async_session_factory
from app.modules.shorts_auto_product.eval.enumeration_score import (
    GoldenSet,
    JaccardLabelMatcher,
    enumeration_precision,
    enumeration_recall,
    evaluate_gates,
)
from app.modules.shorts_auto_product.eval.window_score import (
    VideoWindowReport,
    aggregate_mean_iou_across_videos,
    evaluate_window_gates,
    score_video as window_score_video,
)

_VALID_SOURCES = ("vision", "overlay", "all")


# ---------- types ----------


@dataclass
class CatalogRow:
    """One active catalog entry pulled from Postgres for a video."""

    llm_label: str
    enumeration_source: str
    enumeration_version: str
    enumeration_prompt_version: str


@dataclass
class WindowProductDetail:
    """Per-product window-scoring breakdown for the markdown report.

    Surfaced so a failing aggregate IoU can be diagnosed without
    rerunning — the operator sees WHICH products tanked the mean.
    """

    label_kr: str
    has_ground_truth: bool
    has_picker_run: bool
    coverage_recall: float | None
    selection_precision: float | None
    iou: float | None
    expected_total_ms: int
    actual_total_ms: int
    intersection_ms: int


@dataclass
class VideoResult:
    """Per-video eval result."""

    video_id: str
    category: str
    source_filter: str
    expected_count: int
    actual_count: int
    negatives_count: int
    recall: float
    precision: float
    gates: dict
    # Version drift: distinct (enumeration_version, prompt_version) seen
    # on the live catalog rows vs the golden's declared versions.
    version_drift: list[str]
    # Window-score block — populated when --skip-window-score is OFF.
    # ``mean_iou`` is ``None`` when no products on this video had BOTH
    # ground-truth windows AND a historical picker run.
    window_mean_iou: float | None = None
    window_mean_coverage_recall: float | None = None
    window_mean_selection_precision: float | None = None
    window_products_graded: int = 0
    window_products_ungradeable: int = 0
    window_products_no_picker_history: int = 0
    window_per_product: list[WindowProductDetail] = field(default_factory=list)
    # Version drift: distinct (enumeration_version, prompt_version) seen
    # on the live catalog rows vs the golden's declared versions.
    version_drift: list[str]


# ---------- DB plumbing ----------


async def _load_catalog_rows(
    *, org_slug: str, video_id: str, source: str
) -> list[CatalogRow]:
    """Active catalog entries for (org, video), optionally source-filtered.

    ``source`` is one of ``vision`` / ``overlay`` / ``all``. ``all`` does
    NOT restrict ``enumeration_source`` (grades the unified catalog).
    """
    where_source = ""
    params: dict[str, object] = {"slug": org_slug, "vid": video_id}
    if source != "all":
        where_source = "AND pce.enumeration_source = :source"
        params["source"] = source

    sf = get_async_session_factory()
    async with sf() as s:
        rows = (
            await s.execute(
                text(
                    f"""
                    SELECT pce.llm_label AS label,
                           pce.enumeration_source AS source,
                           pce.enumeration_version AS ver,
                           pce.enumeration_prompt_version AS prompt_ver
                    FROM product_catalog_entries pce
                    JOIN drive_files df ON df.id = pce.video_id
                    JOIN orgs o ON o.id = df.org_id
                    WHERE pce.rejected_at IS NULL
                      AND df.is_deleted = false
                      AND df.video_id = :vid
                      AND o.slug = :slug
                      {where_source}
                    ORDER BY pce.llm_label
                    """
                ),
                params,
            )
        ).all()
    return [
        CatalogRow(
            llm_label=r.label or "",
            enumeration_source=r.source or "",
            enumeration_version=r.ver or "",
            enumeration_prompt_version=r.prompt_ver or "",
        )
        for r in rows
    ]


def _extract_picker_windows_from_spec(
    spec: dict | None, target_video_id: str
) -> list[tuple[int, int]]:
    """Pure: pull source-video [start_ms, end_ms) windows out of one
    composition spec, filtered to clips that came from ``target_video_id``.

    Composition specs can carry clips from MULTIPLE source videos (multi-
    source comp); we drop clips whose ``video_id`` doesn't match so the
    picker isn't credited for time it drew from a different source.
    Inverted / zero-duration clips are dropped defensively — the scorer
    drops them too, but doing it here keeps the report counts honest.
    Unit-tested in ``tests/test_eval_shorts_auto_product.py``.
    """
    if not isinstance(spec, dict):
        return []
    clips = spec.get("scene_clips") or []
    out: list[tuple[int, int]] = []
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        if clip.get("video_id") != target_video_id:
            continue
        try:
            s_ms = int(clip["start_ms"])
            e_ms = int(clip["end_ms"])
        except (KeyError, TypeError, ValueError):
            continue
        if e_ms > s_ms:
            out.append((s_ms, e_ms))
    return out


async def _load_picker_windows_for_video(
    *, org_slug: str, video_id: str
) -> dict[str, list[tuple[int, int]]]:
    """LATEST picker output per (video, product), keyed by catalog label.

    Joins ``shorts_render_jobs`` → ``product_scan_jobs`` (mode='render_child')
    → ``product_catalog_entries`` to recover the operator-selected product
    behind each historical short. For each ``(org, video_id, catalog_entry)``
    triple we keep ONLY the most recent render_child (per the LATEST
    aggregation choice in goldens/README.md) and return its scene_clips'
    source-video [start_ms, end_ms) windows.

    ``scene_clips`` can compose clips from multiple source videos
    (cross-video composition); we filter to clips whose ``video_id``
    matches the target video so the picker is graded only on time it
    drew from THIS source.

    Returns ``{label_kr: [(start_ms, end_ms), ...]}``. Products with no
    historical picker run are simply absent from the dict — the caller
    distinguishes them from "picker emitted nothing" via this absence.
    """
    sf = get_async_session_factory()
    async with sf() as s:
        rows = (
            await s.execute(
                text(
                    """
                    -- LATEST render_child per (org, video, catalog_entry).
                    -- DISTINCT ON keeps the row whose srj.created_at is
                    -- newest within each (catalog_entry_id) bucket; the
                    -- outer ORDER BY enforces that within-bucket ordering.
                    SELECT DISTINCT ON (psj.catalog_entry_id)
                           pce.llm_label    AS label,
                           srj.input_spec   AS spec,
                           srj.created_at   AS render_created_at
                    FROM shorts_render_jobs srj
                    JOIN product_scan_jobs psj
                      ON psj.render_job_id = srj.id
                    JOIN product_catalog_entries pce
                      ON pce.id = psj.catalog_entry_id
                    JOIN drive_files df
                      ON df.id = pce.video_id
                    JOIN orgs o
                      ON o.id = df.org_id
                    WHERE psj.mode = 'render_child'
                      AND df.video_id = :vid
                      AND o.slug = :slug
                      AND pce.rejected_at IS NULL
                      AND df.is_deleted = false
                    ORDER BY psj.catalog_entry_id,
                             srj.created_at DESC
                    """
                ),
                {"slug": org_slug, "vid": video_id},
            )
        ).all()

    out: dict[str, list[tuple[int, int]]] = {}
    for row in rows:
        label = row.label or ""
        if not label:
            continue
        # ``input_spec`` is the CompositionSpec dict — its ``scene_clips``
        # carry the picker's source-video selections. Parsing is pure
        # and unit-tested separately.
        windows = _extract_picker_windows_from_spec(row.spec, video_id)
        # Aggregate by label — the same label CAN appear twice if the
        # DISTINCT ON bucket boundary changes across multiple catalog
        # entries (e.g. an old + new enumeration_version produced two
        # catalog rows with the same llm_label). Merge their windows so
        # the scorer sees one timeline per label.
        out.setdefault(label, []).extend(windows)
    return out


# ---------- golden loading ----------


def _load_goldens(
    *, golden_dir: Path | None, video_ids: list[str] | None, org_slug: str
) -> list[GoldenSet]:
    """Load goldens from the category folders under ``golden_dir``.

    When ``video_ids`` is given, only goldens for those videos are kept;
    otherwise every golden in the directory tree is loaded. Goldens for
    other orgs are skipped. The ``storyboard/`` folder (clip-window
    fixtures, not enumeration goldens) is skipped.
    """
    if golden_dir is None:
        return []
    if not golden_dir.exists():
        raise FileNotFoundError(f"golden dir not found: {golden_dir}")

    wanted = set(video_ids or [])
    goldens: list[GoldenSet] = []
    for path in sorted(golden_dir.rglob("*.json")):
        # storyboard fixtures are not enumeration goldens.
        if "storyboard" in path.parts:
            continue
        if path.name.startswith("_"):  # _TEMPLATE.json etc.
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[eval] skip {path}: {e}", file=sys.stderr)
            continue
        if "video_id" not in raw or "expected_products" not in raw:
            continue  # not an enumeration golden
        golden = GoldenSet.from_dict(raw)
        if golden.org_slug != org_slug:
            continue
        if wanted and golden.video_id not in wanted:
            continue
        goldens.append(golden)
    return goldens


def _version_drift(golden: GoldenSet, rows: list[CatalogRow]) -> list[str]:
    """Return drift messages where live catalog versions disagree.

    "Live" = the versions actually stamped on the catalog rows the worker
    produced (each row carries its own ``enumeration_version`` +
    ``enumeration_prompt_version``). Empty list = no drift.
    """
    drift: list[str] = []
    live_versions = {r.enumeration_version for r in rows if r.enumeration_version}
    live_prompt_versions = {
        r.enumeration_prompt_version for r in rows if r.enumeration_prompt_version
    }
    if (
        golden.enumeration_version
        and live_versions
        and golden.enumeration_version not in live_versions
    ):
        drift.append(
            f"enumeration_version: golden={golden.enumeration_version!r} "
            f"live={sorted(live_versions)!r}"
        )
    if (
        golden.enumeration_prompt_version
        and live_prompt_versions
        and golden.enumeration_prompt_version not in live_prompt_versions
    ):
        drift.append(
            f"enumeration_prompt_version: "
            f"golden={golden.enumeration_prompt_version!r} "
            f"live={sorted(live_prompt_versions)!r}"
        )
    return drift


# ---------- eval loop ----------


async def _eval_video(
    *,
    golden: GoldenSet,
    source: str,
    matcher: JaccardLabelMatcher,
    skip_window_score: bool = False,
) -> VideoResult:
    rows = await _load_catalog_rows(
        org_slug=golden.org_slug, video_id=golden.video_id, source=source
    )
    actual_labels = [r.llm_label for r in rows if r.llm_label]
    recall = enumeration_recall(golden.expected_products, actual_labels, matcher)
    precision = enumeration_precision(
        actual_labels, golden.expected_negatives, matcher
    )
    gates = evaluate_gates(recall, precision)

    result = VideoResult(
        video_id=golden.video_id,
        category=golden.category,
        source_filter=source,
        expected_count=len(golden.expected_products),
        actual_count=len(actual_labels),
        negatives_count=len(golden.expected_negatives),
        recall=recall,
        precision=precision,
        gates=gates,
        version_drift=_version_drift(golden, rows),
    )

    if skip_window_score:
        return result

    # ── Window-score pass ────────────────────────────────────────────
    # Pull the LATEST historical picker run per (video, product) and
    # grade its scene_clips against the golden's expected_windows_ms.
    picker_windows = await _load_picker_windows_for_video(
        org_slug=golden.org_slug, video_id=golden.video_id
    )
    expected_per_product: dict[str, list[tuple[int, int]]] = {
        p.label_kr: [(int(s), int(e)) for s, e in p.expected_windows_ms]
        for p in golden.expected_products
    }
    win_report: VideoWindowReport = window_score_video(
        video_id=golden.video_id,
        expected_per_product=expected_per_product,
        actual_per_product=picker_windows,
    )

    no_picker_history = 0
    per_product_details: list[WindowProductDetail] = []
    for label, score in win_report.per_product.items():
        actual_present = label in picker_windows
        if not actual_present and score is not None:
            no_picker_history += 1
        per_product_details.append(
            WindowProductDetail(
                label_kr=label,
                has_ground_truth=score is not None,
                has_picker_run=actual_present,
                coverage_recall=(
                    score.coverage_recall if score is not None else None
                ),
                selection_precision=(
                    score.selection_precision if score is not None else None
                ),
                iou=score.iou if score is not None else None,
                expected_total_ms=(
                    score.expected_total_ms if score is not None else 0
                ),
                actual_total_ms=(
                    score.actual_total_ms if score is not None else 0
                ),
                intersection_ms=(
                    score.intersection_ms if score is not None else 0
                ),
            )
        )
    # Sort ascending so the lowest-IoU products surface at the top of
    # the report — that's the diagnostic ordering operators want.
    per_product_details.sort(
        key=lambda d: (d.iou if d.iou is not None else 999.0, d.label_kr)
    )

    result.window_mean_iou = win_report.mean_iou
    result.window_mean_coverage_recall = win_report.mean_coverage_recall
    result.window_mean_selection_precision = win_report.mean_selection_precision
    result.window_products_graded = win_report.products_graded
    result.window_products_ungradeable = win_report.products_ungradeable
    result.window_products_no_picker_history = no_picker_history
    result.window_per_product = per_product_details
    return result


# ---------- output ----------


def _fmt_opt(v: float | None, *, fmt: str = ".3f") -> str:
    return "n/a" if v is None else format(v, fmt)


def _format_markdown(
    results: list[VideoResult],
    *,
    org_slug: str,
    source: str,
    threshold: float,
    aggregate_gates: dict,
    window_gate: dict | None,
    window_aggregate_iou: float | None,
    window_score_enabled: bool,
    window_score_required: bool,
) -> str:
    lines: list[str] = []
    lines.append(
        f"# Product enumeration eval — org={org_slug} source={source}"
    )
    lines.append("")
    lines.append(f"label-match threshold (token Jaccard): {threshold}")
    lines.append(f"videos evaluated: {len(results)}")
    if window_score_enabled:
        lines.append(
            f"scene-selection scoring: ON "
            f"(gate {'REQUIRED' if window_score_required else 'INFORMATIONAL'})"
        )
    else:
        lines.append("scene-selection scoring: OFF (--skip-window-score)")
    lines.append("")
    lines.append("## Per-video — enumeration")
    lines.append("")
    lines.append(
        "| video_id | category | expected | actual | neg | recall | "
        "precision | gates |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in results:
        verdict = "PASS" if r.gates["passed"] else "FAIL"
        lines.append(
            f"| {r.video_id} | {r.category} | {r.expected_count} | "
            f"{r.actual_count} | {r.negatives_count} | {r.recall:.3f} | "
            f"{r.precision:.3f} | {verdict} |"
        )
    lines.append("")

    drift_rows = [r for r in results if r.version_drift]
    if drift_rows:
        lines.append("## Version drift (ran with --allow-version-drift)")
        lines.append("")
        for r in drift_rows:
            for d in r.version_drift:
                lines.append(f"  - {r.video_id}: {d}")
        lines.append("")

    if window_score_enabled:
        lines.append("## Per-video — scene selection (window scoring)")
        lines.append("")
        lines.append(
            "| video_id | mean IoU | mean recall | mean precision | "
            "graded | ungradeable | no-picker-history |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for r in results:
            lines.append(
                f"| {r.video_id} | {_fmt_opt(r.window_mean_iou)} | "
                f"{_fmt_opt(r.window_mean_coverage_recall)} | "
                f"{_fmt_opt(r.window_mean_selection_precision)} | "
                f"{r.window_products_graded} | "
                f"{r.window_products_ungradeable} | "
                f"{r.window_products_no_picker_history} |"
            )
        lines.append("")

        # Per-product breakdown sorted IoU-ascending — failing products
        # surface at the top so the operator sees the worst offenders
        # without scrolling.
        for r in results:
            if not r.window_per_product:
                continue
            lines.append(f"### {r.video_id} — per-product window detail")
            lines.append("")
            lines.append(
                "| product | iou | coverage_recall | selection_precision "
                "| expected_ms | actual_ms | inter_ms | note |"
            )
            lines.append("|---|---|---|---|---|---|---|---|")
            for d in r.window_per_product:
                if not d.has_ground_truth:
                    note = "no ground-truth windows"
                elif not d.has_picker_run:
                    note = "no historical picker run"
                else:
                    note = ""
                lines.append(
                    f"| {d.label_kr} | {_fmt_opt(d.iou)} | "
                    f"{_fmt_opt(d.coverage_recall)} | "
                    f"{_fmt_opt(d.selection_precision)} | "
                    f"{d.expected_total_ms} | {d.actual_total_ms} | "
                    f"{d.intersection_ms} | {note} |"
                )
            lines.append("")

    lines.append("## Aggregate gates")
    lines.append("")
    rec = aggregate_gates["recall"]
    prec = aggregate_gates["precision"]
    lines.append(
        f"  enumeration recall:    {rec['value']:.3f} "
        f"(floor {rec['floor']}) -> {'PASS' if rec['passed'] else 'FAIL'}"
    )
    if rec["failure_action"]:
        lines.append(f"      action: {rec['failure_action']}")
    lines.append(
        f"  enumeration precision: {prec['value']:.3f} "
        f"(floor {prec['floor']}) -> {'PASS' if prec['passed'] else 'FAIL'}"
    )
    if prec["failure_action"]:
        lines.append(f"      action: {prec['failure_action']}")
    if window_score_enabled and window_gate is not None:
        gate_verdict = "PASS" if window_gate["passed"] else "FAIL"
        gate_label = "gate" if window_score_required else "info-only"
        iou_val = (
            f"{window_aggregate_iou:.3f}"
            if window_aggregate_iou is not None
            else "n/a"
        )
        lines.append(
            f"  window IoU (mean):     {iou_val} "
            f"(floor {window_gate['floor']}) -> {gate_verdict} [{gate_label}]"
        )
        if window_gate["failure_action"]:
            lines.append(f"      action: {window_gate['failure_action']}")
    lines.append("")

    # Overall = enumeration always required; window only required when
    # the flag is set. This matches the operator's first-baseline use
    # case (run the harness, see the IoU number, don't fail the exit).
    overall_pass = aggregate_gates["passed"]
    if window_score_enabled and window_score_required and window_gate is not None:
        overall_pass = overall_pass and window_gate["passed"]
    lines.append(f"## Overall: {'PASS' if overall_pass else 'FAIL'}")
    lines.append("")
    return "\n".join(lines)


# ---------- main ----------


async def _run(args: argparse.Namespace) -> int:
    golden_dir = Path(args.golden_dir) if args.golden_dir else None
    matcher = JaccardLabelMatcher(threshold=args.label_match_threshold)

    try:
        goldens = _load_goldens(
            golden_dir=golden_dir,
            video_ids=args.video_id or None,
            org_slug=args.org_slug,
        )
    except FileNotFoundError as e:
        print(f"[eval] {e}", file=sys.stderr)
        return 2

    if not goldens:
        print(
            f"[eval] no enumeration goldens matched org={args.org_slug!r} "
            f"video_id={args.video_id or 'ANY'} in {golden_dir}",
            file=sys.stderr,
        )
        return 2

    print(f"[eval] {len(goldens)} golden(s); source={args.source}", file=sys.stderr)

    results: list[VideoResult] = []
    for golden in goldens:
        try:
            r = await _eval_video(
                golden=golden,
                source=args.source,
                matcher=matcher,
                skip_window_score=args.skip_window_score,
            )
        except Exception as e:  # noqa: BLE001
            print(
                f"[eval] video {golden.video_id} failed: {e}", file=sys.stderr
            )
            return 2
        results.append(r)

    # Version-drift gate (per README): refuse to run if any golden's
    # versions disagree with live, unless --allow-version-drift.
    drift_videos = [r for r in results if r.version_drift]
    if drift_videos and not args.allow_version_drift:
        print(
            "[eval] version drift detected (use --allow-version-drift to "
            "score anyway):",
            file=sys.stderr,
        )
        for r in drift_videos:
            for d in r.version_drift:
                print(f"  - {r.video_id}: {d}", file=sys.stderr)
        return 2

    # Aggregate recall/precision = mean across videos (each video is one
    # golden; videos with no expected products contribute recall 1.0).
    n = len(results)
    agg_recall = sum(r.recall for r in results) / n
    agg_precision = sum(r.precision for r in results) / n
    aggregate_gates = evaluate_gates(agg_recall, agg_precision)

    # Aggregate window IoU across videos. ``VideoWindowReport`` is what
    # window_score.aggregate_mean_iou_across_videos consumes — synthesize
    # one per video result so the cross-video mean honors the ungradeable-
    # exclusion semantics from window_score (rather than mixing None and
    # 0.0 by hand here).
    if args.skip_window_score:
        window_aggregate_iou: float | None = None
        window_gate: dict | None = None
    else:
        synthesized_reports = [
            VideoWindowReport(
                video_id=r.video_id,
                per_product={},  # only mean_iou is consulted
                mean_iou=r.window_mean_iou,
                mean_coverage_recall=r.window_mean_coverage_recall,
                mean_selection_precision=r.window_mean_selection_precision,
                products_graded=r.window_products_graded,
                products_ungradeable=r.window_products_ungradeable,
            )
            for r in results
        ]
        window_aggregate_iou = aggregate_mean_iou_across_videos(
            synthesized_reports
        )
        window_gate = evaluate_window_gates(window_aggregate_iou)

    md = _format_markdown(
        results,
        org_slug=args.org_slug,
        source=args.source,
        threshold=args.label_match_threshold,
        aggregate_gates=aggregate_gates,
        window_gate=window_gate,
        window_aggregate_iou=window_aggregate_iou,
        window_score_enabled=not args.skip_window_score,
        window_score_required=args.window_score_required,
    )
    print(md)

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "org_slug": args.org_slug,
                    "source": args.source,
                    "label_match_threshold": args.label_match_threshold,
                    "aggregate_gates": aggregate_gates,
                    "window_score_enabled": not args.skip_window_score,
                    "window_score_required": args.window_score_required,
                    "window_aggregate_iou": window_aggregate_iou,
                    "window_gate": window_gate,
                    "videos": [asdict(r) for r in results],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[eval] JSON written to {args.out}", file=sys.stderr)

    # Exit code policy:
    #   * enumeration gates ALWAYS gate the exit.
    #   * window gate gates the exit ONLY when --window-score-required.
    #     Default behaviour is informational — the first staging baseline
    #     measurement runs to completion without failing the build, so
    #     the operator can see the IoU number and tune from there.
    overall_pass = aggregate_gates["passed"]
    if (
        not args.skip_window_score
        and args.window_score_required
        and window_gate is not None
    ):
        overall_pass = overall_pass and window_gate["passed"]
    return 0 if overall_pass else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Product enumeration eval harness (vision + overlay). "
        "Scores active product_catalog_entries against curated goldens.",
    )
    parser.add_argument(
        "--org-slug",
        required=True,
        help="Org slug (e.g., 'devorg').",
    )
    parser.add_argument(
        "--video-id",
        action="append",
        default=[],
        help="Restrict to specific video_id(s) (gd_*). Repeatable. "
        "When omitted, every golden in --golden-dir is graded.",
    )
    parser.add_argument(
        "--golden-dir",
        default="tests/shorts_auto_product/eval/goldens",
        help="Goldens root (default: tests/shorts_auto_product/eval/goldens). "
        "Loads from cosmetics/, fashion/, food/, overlay/.",
    )
    parser.add_argument(
        "--source",
        choices=_VALID_SOURCES,
        default="all",
        help="Filter the catalog query on enumeration_source. "
        "'all' grades the unified vision+overlay+stt catalog (default).",
    )
    parser.add_argument(
        "--label-match-threshold",
        type=float,
        default=0.5,
        help="Token-Jaccard threshold for the deterministic label matcher "
        "(default: 0.5).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional JSON output path. Markdown always goes to stdout.",
    )
    parser.add_argument(
        "--allow-version-drift",
        action="store_true",
        help="Score even when a golden's enumeration_(prompt_)version "
        "disagrees with the live catalog rows. Default: refuse (exit 2).",
    )
    parser.add_argument(
        "--skip-window-score",
        action="store_true",
        help="Skip the scene-selection window scoring pass. By default "
        "window scoring runs alongside enumeration; pass this flag when "
        "you only need the enumeration gate (faster — skips the "
        "picker-window DB query).",
    )
    parser.add_argument(
        "--window-score-required",
        action="store_true",
        help="Fail the run (exit 1) when the window-IoU floor is missed. "
        "Default: informational — the window pass is graded and reported "
        "but does NOT affect the exit code. Flip this on once the floor "
        "is realistic (current floor: 0.60).",
    )
    args = parser.parse_args()
    if not args.video_id and not args.golden_dir:
        parser.error("provide --golden-dir or at least one --video-id")
    return args


def main() -> int:
    args = _parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 2


if __name__ == "__main__":
    sys.exit(main())
