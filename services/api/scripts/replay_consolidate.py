"""Replay the catalog-consolidate LLM call against a frozen input snapshot.

The consolidate prompt is the only thing we want to iterate on; rerunning
the entire vision+overlay+STT enumeration pipeline per prompt version
costs real Aircloud GPU + OpenAI money + ~5-10 min wall clock per video.
This CLI separates the two:

  1. ``snapshot``: capture the PRE-CONSOLIDATE catalog input set for a
     video (the exact rows ``run_consolidation`` would feed to the LLM)
     to a JSON file. Refuses to run if consolidate has ALREADY fired for
     that video — the only honest snapshot is one taken before
     consolidate touched the rows.
  2. ``replay``: load a snapshot + a target ``--prompt-version`` →
     instantiate ``CatalogConsolidator(prompt_version=...)`` → call the
     PURE ``consolidate()`` method → emit a verdict-map JSON. No DB
     writes. Repeatable; you can replay v2.2 → v2.3 → v2.4 against the
     same snapshot indefinitely.

Pair with ``score_verdict_map.py`` to grade the verdict-map JSON
against the goldens at ``tests/shorts_auto_product/eval/goldens/`` and
check the enumeration-recall / enumeration-precision cal gates.

Runs INSIDE the api container (needs DB access via ``app.*``).

Usage::

    # Operator workflow (capture once, replay many)
    ssh -i ~/.ssh/heimdex-staging.pem ec2-user@3.34.75.63
    cd /opt/heimdex/dev-heimdex-for-livecommerce

    # 1. Trigger a fresh rescan from the wizard. Within the 105s
    #    consolidate-grace window, capture the snapshot:
    docker compose exec -T api python -m scripts.replay_consolidate snapshot \\
        --org-slug devorg \\
        --video-id gd_d24cb28631262130 \\
        --out /tmp/snap_jongga.json

    # 2. Replay any prompt version against the frozen snapshot. NO
    #    rescan, NO DB writes, just an LLM call.
    docker compose exec -T api python -m scripts.replay_consolidate replay \\
        --snapshot /tmp/snap_jongga.json \\
        --prompt-version v2.2-test-iteration \\
        --out /tmp/replay_v22_jongga.json

    # 3. Score it (see score_verdict_map.py):
    docker compose exec -T api python -m scripts.score_verdict_map \\
        --verdict-map /tmp/replay_v22_jongga.json \\
        --golden tests/shorts_auto_product/eval/goldens/food/devorg_gd_d24cb28631262130.json

Exit codes:
    0 — subcommand completed cleanly
    1 — operator-recoverable error (consolidate already ran on this video
        → rescan + retry; snapshot file missing → check path)
    2 — runner / config error (DB unreachable, missing OPENAI_API_KEY,
        bad args)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.base import get_async_session_factory
from app.modules.shorts_auto_product.consolidate.llm_consolidator import (
    _DEFAULT_PROMPT_VERSION,
    CatalogConsolidator,
    CatalogConsolidatorInput,
    ConsolidationGroup,
    ConsolidationRejection,
    ConsolidationResult,
)
from app.modules.shorts_auto_product.consolidate.service import (
    _build_host_spoken_terms,
)
from app.modules.shorts_auto_product.models import ProductCatalogEntry
from app.modules.shorts_auto_product.repositories.catalog import (
    ProductCatalogRepository,
)

_SCHEMA_VERSION = 1


# ---------- dataclasses (JSON-serializable wire format) ----------


@dataclass(frozen=True)
class _SnapshotEntry:
    """One pre-consolidate catalog row, JSON-friendly."""

    entry_id: str  # UUID stringified
    llm_label: str
    spoken_aliases: list[str]
    source: str  # vision | overlay | stt
    confidence: float
    example_quote: str | None


@dataclass(frozen=True)
class _Snapshot:
    """Frozen pre-consolidate state for a (org, video). Persisted as JSON."""

    schema_version: int
    video_id: str          # public gd_... id
    video_db_id: str       # internal uuid
    org_id: str
    org_slug: str
    snapshotted_at: str    # ISO8601 UTC
    entries: list[_SnapshotEntry]
    host_spoken_terms: list[str]


@dataclass(frozen=True)
class _VerdictGroup:
    canonical_entry_id: str
    canonical_label: str
    canonical_aliases: list[str]
    member_entry_ids: list[str]
    stt_match_term: str | None = None
    stt_match_score: float | None = None


@dataclass(frozen=True)
class _VerdictRejection:
    entry_id: str
    category: str


@dataclass(frozen=True)
class _VerdictMap:
    """Verdict-map JSON: the LLM's per-row decisions under a given prompt."""

    schema_version: int
    video_id: str
    video_db_id: str
    org_slug: str
    snapshot_path: str
    prompt_version: str
    model: str
    replayed_at: str
    input_count: int
    groups: list[_VerdictGroup]
    rejections: list[_VerdictRejection]
    cost_usd: float
    latency_ms: int


# ---------- snapshot subcommand ----------


async def _resolve_org_and_video(
    *, org_slug: str, video_public_id: str,
) -> tuple[UUID, UUID]:
    """Resolve ``(org_slug, video_public_id)`` → ``(org_id, video_db_id)``.
    Raises ``LookupError`` if either is missing or soft-deleted.
    """
    sf = get_async_session_factory()
    async with sf() as s:
        row = (
            await s.execute(
                text(
                    """
                    SELECT o.id AS org_id, df.id AS video_db_id
                    FROM drive_files df
                    JOIN orgs o ON o.id = df.org_id
                    WHERE df.video_id = :vid
                      AND o.slug = :slug
                      AND df.is_deleted = false
                    """
                ),
                {"vid": video_public_id, "slug": org_slug},
            )
        ).first()
    if row is None:
        raise LookupError(
            f"no drive_file for org_slug={org_slug!r}, "
            f"video_id={video_public_id!r}"
        )
    return row.org_id, row.video_db_id


async def _do_snapshot(args: argparse.Namespace) -> int:
    try:
        org_id, video_db_id = await _resolve_org_and_video(
            org_slug=args.org_slug, video_public_id=args.video_id,
        )
    except LookupError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    sf = get_async_session_factory()
    async with sf() as session:
        repo = ProductCatalogRepository(session)
        # Guard: consolidate already fired = pre-consolidate state is
        # lost. Operator must rescan to get a clean snapshot.
        if await repo.has_consolidation_markers(
            org_id=org_id, video_id=video_db_id,
        ):
            print(
                f"ERROR: video {args.video_id!r} already has consolidation "
                "markers; pre-consolidate state is gone. Rescan via the "
                "wizard, then run this snapshot within the 105s "
                "consolidate-grace window. See "
                "feedback_enqueue_scan_dedups_use_rescan — use 'rescan' "
                "not 'enqueue_scan'.",
                file=sys.stderr,
            )
            return 1
        entries: list[ProductCatalogEntry] = await repo.list_active_by_video(
            org_id=org_id, video_id=video_db_id,
        )

    if len(entries) <= 1:
        print(
            f"WARN: only {len(entries)} active entries; consolidate "
            "would skip this as trivial. Snapshotting anyway.",
            file=sys.stderr,
        )

    snap_entries = [
        _SnapshotEntry(
            entry_id=str(e.id),
            llm_label=e.llm_label,
            spoken_aliases=list(e.spoken_aliases or []),
            source=e.enumeration_source,
            confidence=float(e.enumeration_confidence),
            example_quote=e.example_quote,
        )
        for e in entries
    ]
    host_spoken_terms = _build_host_spoken_terms(entries)

    snap = _Snapshot(
        schema_version=_SCHEMA_VERSION,
        video_id=args.video_id,
        video_db_id=str(video_db_id),
        org_id=str(org_id),
        org_slug=args.org_slug,
        snapshotted_at=datetime.now(timezone.utc).isoformat(),
        entries=snap_entries,
        host_spoken_terms=host_spoken_terms,
    )

    out_path = Path(args.out)
    out_path.write_text(json.dumps(asdict(snap), ensure_ascii=False, indent=2))

    src_counts: dict[str, int] = {}
    for e in snap_entries:
        src_counts[e.source] = src_counts.get(e.source, 0) + 1
    print(
        f"[snapshot] wrote {out_path} — {len(snap_entries)} entries "
        f"({', '.join(f'{k}={v}' for k, v in sorted(src_counts.items()))}), "
        f"{len(host_spoken_terms)} host_spoken_terms"
    )
    return 0


# ---------- replay subcommand ----------


def _load_snapshot(path: Path) -> _Snapshot:
    raw = json.loads(path.read_text())
    if raw.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(
            f"snapshot schema version mismatch — got "
            f"{raw.get('schema_version')!r}, expected {_SCHEMA_VERSION}"
        )
    return _Snapshot(
        schema_version=raw["schema_version"],
        video_id=raw["video_id"],
        video_db_id=raw["video_db_id"],
        org_id=raw["org_id"],
        org_slug=raw["org_slug"],
        snapshotted_at=raw["snapshotted_at"],
        entries=[_SnapshotEntry(**e) for e in raw["entries"]],
        host_spoken_terms=list(raw["host_spoken_terms"]),
    )


def _build_openai_client(*, api_key: str) -> Any:
    """Same shape ``consolidate.service._build_openai_client`` uses."""
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=api_key)


async def _do_replay(args: argparse.Namespace) -> int:
    snap_path = Path(args.snapshot)
    if not snap_path.exists():
        print(f"ERROR: snapshot file not found: {snap_path}", file=sys.stderr)
        return 1
    snap = _load_snapshot(snap_path)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(
            "ERROR: OPENAI_API_KEY env var is empty; cannot call the LLM",
            file=sys.stderr,
        )
        return 2

    consolidator_inputs = [
        CatalogConsolidatorInput(
            entry_id=UUID(e.entry_id),
            llm_label=e.llm_label,
            spoken_aliases=list(e.spoken_aliases),
            source=e.source,
            confidence=e.confidence,
            example_quote=e.example_quote,
        )
        for e in snap.entries
    ]

    openai_client = _build_openai_client(api_key=api_key)
    try:
        consolidator = CatalogConsolidator(
            openai_client=openai_client,
            prompt_version=args.prompt_version,
        )
        try:
            result: ConsolidationResult = await consolidator.consolidate(
                entries=consolidator_inputs,
                host_spoken_terms=list(snap.host_spoken_terms),
            )
        except Exception as e:  # noqa: BLE001 — surface to operator
            print(
                f"ERROR: consolidate LLM call failed: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            return 1
    finally:
        try:
            close = getattr(openai_client, "close", None)
            if close is not None:
                maybe_coro = close()
                if asyncio.iscoroutine(maybe_coro):
                    await maybe_coro
        except Exception:
            pass

    verdict = _VerdictMap(
        schema_version=_SCHEMA_VERSION,
        video_id=snap.video_id,
        video_db_id=snap.video_db_id,
        org_slug=snap.org_slug,
        snapshot_path=str(snap_path),
        prompt_version=args.prompt_version,
        model=result.model,
        replayed_at=datetime.now(timezone.utc).isoformat(),
        input_count=result.raw_input_count,
        groups=[
            _VerdictGroup(
                canonical_entry_id=str(g.canonical_entry_id),
                canonical_label=g.canonical_label,
                canonical_aliases=list(g.canonical_aliases),
                member_entry_ids=[str(m) for m in g.member_entry_ids],
                stt_match_term=g.stt_match_term,
                stt_match_score=g.stt_match_score,
            )
            for g in result.groups
        ],
        rejections=[
            _VerdictRejection(
                entry_id=str(r.entry_id),
                category=r.category,
            )
            for r in result.rejections
        ],
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
    )

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(asdict(verdict), ensure_ascii=False, indent=2),
    )

    # Stdout summary — let the operator eyeball the result without
    # opening the JSON.
    total_rejected = len(verdict.rejections)
    rej_by_cat: dict[str, int] = {}
    for r in verdict.rejections:
        rej_by_cat[r.category] = rej_by_cat.get(r.category, 0) + 1
    cross_source_merges = sum(
        1 for g in verdict.groups if g.member_entry_ids
    )
    print(
        f"[replay] wrote {out_path} — prompt={args.prompt_version} "
        f"input={verdict.input_count} groups={len(verdict.groups)} "
        f"rejected={total_rejected} "
        f"({', '.join(f'{k}={v}' for k, v in sorted(rej_by_cat.items())) or 'none'}) "
        f"groups_with_members={cross_source_merges} "
        f"cost=${verdict.cost_usd:.4f} latency={verdict.latency_ms}ms"
    )
    return 0


# ---------- main ----------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="replay_consolidate",
        description=(
            "Capture pre-consolidate catalog state OR replay the "
            "consolidate LLM call against a captured snapshot."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    snap = sub.add_parser(
        "snapshot",
        help="Capture pre-consolidate catalog inputs for a video (JSON).",
    )
    snap.add_argument("--org-slug", required=True, help="e.g. devorg")
    snap.add_argument(
        "--video-id", required=True,
        help="Public video id, e.g. gd_d24cb28631262130",
    )
    snap.add_argument(
        "--out", required=True,
        help="Output JSON path, e.g. /tmp/snap_jongga.json",
    )

    rep = sub.add_parser(
        "replay",
        help=(
            "Re-run the consolidate LLM against a snapshot with the "
            "specified prompt_version (no DB writes)."
        ),
    )
    rep.add_argument("--snapshot", required=True, help="snapshot JSON path")
    rep.add_argument(
        "--prompt-version", default=_DEFAULT_PROMPT_VERSION,
        help=(
            "Override the prompt_version stamped on the verdict map. "
            "Defaults to the code's current "
            "_DEFAULT_PROMPT_VERSION. Note: the prompt BODY is whatever "
            "lives in llm_consolidator.py right now; this flag only "
            "tags the verdict map for downstream comparison. Change the "
            "prompt body in code before each replay batch when iterating."
        ),
    )
    rep.add_argument(
        "--out", required=True,
        help="Verdict map JSON output path, e.g. /tmp/replay_v22_jongga.json",
    )

    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.cmd == "snapshot":
        return asyncio.run(_do_snapshot(args))
    if args.cmd == "replay":
        return asyncio.run(_do_replay(args))
    return 2


if __name__ == "__main__":
    sys.exit(main())
