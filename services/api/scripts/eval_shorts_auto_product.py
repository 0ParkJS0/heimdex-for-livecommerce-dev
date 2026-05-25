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
from dataclasses import asdict, dataclass
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
    return VideoResult(
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


# ---------- output ----------


def _format_markdown(
    results: list[VideoResult],
    *,
    org_slug: str,
    source: str,
    threshold: float,
    aggregate_gates: dict,
) -> str:
    lines: list[str] = []
    lines.append(
        f"# Product enumeration eval — org={org_slug} source={source}"
    )
    lines.append("")
    lines.append(f"label-match threshold (token Jaccard): {threshold}")
    lines.append(f"videos evaluated: {len(results)}")
    lines.append("")
    lines.append("## Per-video")
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
    lines.append("")
    overall = "PASS" if aggregate_gates["passed"] else "FAIL"
    lines.append(f"## Overall: {overall}")
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
                golden=golden, source=args.source, matcher=matcher
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

    md = _format_markdown(
        results,
        org_slug=args.org_slug,
        source=args.source,
        threshold=args.label_match_threshold,
        aggregate_gates=aggregate_gates,
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
                    "videos": [asdict(r) for r in results],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[eval] JSON written to {args.out}", file=sys.stderr)

    return 0 if aggregate_gates["passed"] else 1


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
