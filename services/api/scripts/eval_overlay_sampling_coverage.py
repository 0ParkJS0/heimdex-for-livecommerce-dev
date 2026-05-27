"""Evaluate overlay-golden coverage under the product-enum keyframe sampler.

This is a diagnostic harness, not a product endpoint. It answers the
first recall question before detector / VLM / clustering are involved:

    "Did the current worker keyframe sampling even look inside each
    golden overlay product window?"

Run inside the API container so it uses the same OpenSearch alias and
settings as staging:

    docker compose exec -T api python -m scripts.eval_overlay_sampling_coverage \
        --org-slug devorg \
        --golden-dir tests/shorts_auto_product/eval/goldens/overlay \
        --max-keyframes 60 \
        --out /tmp/overlay_sampling_coverage.json

The sampling rule intentionally mirrors product-enumerate-worker
``_fetch_keyframes``: uniform scene subsampling by index with
``raw_scenes[int(i * stride)]`` when scene_count > max_keyframes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.modules.search.scene_client import SceneSearchClient
from scripts.eval_shorts_auto_product import _load_goldens


@dataclass(frozen=True)
class SampledScene:
    scene_id: str
    start_ms: int
    end_ms: int
    sample_ms: int
    sample_source: str
    ocr_char_count: int


@dataclass(frozen=True)
class WindowCoverage:
    start_ms: int
    end_ms: int
    covered: bool
    sampled_ms_inside: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ProductCoverage:
    label_kr: str
    category_hint: str | None
    expected_window_count: int
    covered_window_count: int
    covered: bool
    expected_total_ms: int
    covered_total_ms: int
    first_appearance_ms: int | None
    windows: list[WindowCoverage]


@dataclass(frozen=True)
class VideoCoverage:
    video_id: str
    category: str
    scene_count: int
    sampled_count: int
    max_keyframes: int
    product_count: int
    products_covered: int
    window_count: int
    windows_covered: int
    product_coverage: float
    window_coverage: float
    sampled_scenes: list[SampledScene]
    products: list[ProductCoverage]


def _sample_scenes(raw_scenes: list[dict[str, Any]], max_keyframes: int) -> list[dict[str, Any]]:
    if max_keyframes <= 0:
        raise ValueError("--max-keyframes must be positive")
    if len(raw_scenes) > max_keyframes:
        stride = len(raw_scenes) / max_keyframes
        return [raw_scenes[int(i * stride)] for i in range(max_keyframes)]
    return list(raw_scenes)


def _scene_sample_ms(scene: dict[str, Any]) -> tuple[int, str]:
    raw = scene.get("keyframe_timestamp_ms")
    if isinstance(raw, int) and raw > 0:
        return raw, "keyframe_timestamp_ms"
    start = int(scene.get("start_ms") or 0)
    end = int(scene.get("end_ms") or start)
    return start + max(0, end - start) // 2, "scene_midpoint_fallback"


def _interval_intersection_ms(a: tuple[int, int], b: tuple[int, int]) -> int:
    start = max(a[0], b[0])
    end = min(a[1], b[1])
    return max(0, end - start)


async def _load_video_scenes(
    client: SceneSearchClient,
    *,
    org_id: str,
    video_id: str,
) -> list[dict[str, Any]]:
    page_size = 500
    offset = 0
    scenes: list[dict[str, Any]] = []
    while True:
        response = await client.get_video_scenes(
            org_id=org_id,
            video_id=video_id,
            page_size=page_size,
            offset=offset,
        )
        batch = response.get("scenes", [])
        if not batch:
            break
        scenes.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    scenes.sort(key=lambda s: int(s.get("start_ms") or 0))
    return scenes


def _score_product(
    product: Any,
    sampled: list[SampledScene],
) -> ProductCoverage:
    windows: list[WindowCoverage] = []
    covered_total_ms = 0
    expected_total_ms = 0

    for start_raw, end_raw in product.expected_windows_ms:
        start_ms = int(start_raw)
        end_ms = int(end_raw)
        if end_ms <= start_ms:
            continue
        expected_total_ms += end_ms - start_ms
        inside = [
            s.sample_ms
            for s in sampled
            if start_ms <= s.sample_ms < end_ms
        ]
        covered = bool(inside)
        if covered:
            # Coverage ceiling for a sampled point means "this window can
            # be observed", so count the full expected window for product-
            # level ceiling. The exact temporal IoU belongs to picker eval.
            covered_total_ms += end_ms - start_ms
        windows.append(
            WindowCoverage(
                start_ms=start_ms,
                end_ms=end_ms,
                covered=covered,
                sampled_ms_inside=inside,
            )
        )

    covered_window_count = sum(1 for w in windows if w.covered)
    return ProductCoverage(
        label_kr=product.label_kr,
        category_hint=product.category_hint,
        expected_window_count=len(windows),
        covered_window_count=covered_window_count,
        covered=covered_window_count > 0,
        expected_total_ms=expected_total_ms,
        covered_total_ms=covered_total_ms,
        first_appearance_ms=product.first_appearance_ms,
        windows=windows,
    )


async def _eval_video(
    *,
    client: SceneSearchClient,
    org_id: str,
    golden: Any,
    max_keyframes: int,
) -> VideoCoverage:
    scenes = await _load_video_scenes(
        client, org_id=org_id, video_id=golden.video_id,
    )
    sampled_raw = _sample_scenes(scenes, max_keyframes)
    sampled: list[SampledScene] = []
    for scene in sampled_raw:
        sample_ms, sample_source = _scene_sample_ms(scene)
        sampled.append(
            SampledScene(
                scene_id=str(scene.get("scene_id") or ""),
                start_ms=int(scene.get("start_ms") or 0),
                end_ms=int(scene.get("end_ms") or 0),
                sample_ms=sample_ms,
                sample_source=sample_source,
                ocr_char_count=int(scene.get("ocr_char_count") or 0),
            )
        )

    products = [
        _score_product(product, sampled)
        for product in golden.expected_products
    ]
    product_count = len(products)
    products_covered = sum(1 for p in products if p.covered)
    window_count = sum(p.expected_window_count for p in products)
    windows_covered = sum(p.covered_window_count for p in products)

    return VideoCoverage(
        video_id=golden.video_id,
        category=golden.category,
        scene_count=len(scenes),
        sampled_count=len(sampled),
        max_keyframes=max_keyframes,
        product_count=product_count,
        products_covered=products_covered,
        window_count=window_count,
        windows_covered=windows_covered,
        product_coverage=(
            products_covered / product_count if product_count else 0.0
        ),
        window_coverage=(
            windows_covered / window_count if window_count else 0.0
        ),
        sampled_scenes=sampled,
        products=products,
    )


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# Overlay sampling coverage — org={report['org_slug']}",
        "",
        f"max_keyframes: `{report['max_keyframes']}`",
        f"videos evaluated: `{len(report['videos'])}`",
        "",
        "## Aggregate",
        "",
        f"- product coverage ceiling: `{report['aggregate']['product_coverage']:.3f}` "
        f"({report['aggregate']['products_covered']}/{report['aggregate']['product_count']})",
        f"- window coverage ceiling: `{report['aggregate']['window_coverage']:.3f}` "
        f"({report['aggregate']['windows_covered']}/{report['aggregate']['window_count']})",
        "",
        "## Per Video",
        "",
        "| video_id | scenes | sampled | products covered | windows covered |",
        "|---|---:|---:|---:|---:|",
    ]
    for video in report["videos"]:
        lines.append(
            f"| {video['video_id']} | {video['scene_count']} | "
            f"{video['sampled_count']} | "
            f"{video['products_covered']}/{video['product_count']} "
            f"({video['product_coverage']:.3f}) | "
            f"{video['windows_covered']}/{video['window_count']} "
            f"({video['window_coverage']:.3f}) |"
        )

    for video in report["videos"]:
        lines.extend(["", f"### {video['video_id']}", ""])
        lines.append("| product | windows covered | covered |")
        lines.append("|---|---:|---|")
        for product in video["products"]:
            lines.append(
                f"| {product['label_kr']} | "
                f"{product['covered_window_count']}/{product['expected_window_count']} | "
                f"{'yes' if product['covered'] else 'no'} |"
            )
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    org_id = args.org_id or ""
    if not org_id:
        # Avoid importing Org models unless the operator asks for slug
        # resolution. The eval harnesses generally run by slug, but
        # OpenSearch scene docs are keyed by UUID.
        from sqlalchemy import select

        from app.db.base import get_async_session_factory
        from app.modules.orgs.models import Org

        sf = get_async_session_factory()
        async with sf() as session:
            org = (
                await session.execute(select(Org).where(Org.slug == args.org_slug))
            ).scalar_one_or_none()
            if org is None:
                raise RuntimeError(f"org not found: {args.org_slug}")
            org_id = str(org.id)

    goldens = _load_goldens(
        golden_dir=args.golden_dir,
        video_ids=args.video_id or None,
        org_slug=args.org_slug,
    )
    if not goldens:
        print("[sampling] no goldens matched", file=sys.stderr)
        return 2

    client = SceneSearchClient()
    try:
        videos = [
            await _eval_video(
                client=client,
                org_id=org_id,
                golden=golden,
                max_keyframes=args.max_keyframes,
            )
            for golden in goldens
        ]
    finally:
        await client.close()

    product_count = sum(v.product_count for v in videos)
    products_covered = sum(v.products_covered for v in videos)
    window_count = sum(v.window_count for v in videos)
    windows_covered = sum(v.windows_covered for v in videos)
    report = {
        "org_slug": args.org_slug,
        "org_id": org_id,
        "golden_dir": str(args.golden_dir),
        "max_keyframes": args.max_keyframes,
        "scene_index_alias": f"{settings.opensearch_index_prefix}_scenes",
        "aggregate": {
            "product_count": product_count,
            "products_covered": products_covered,
            "product_coverage": (
                products_covered / product_count if product_count else 0.0
            ),
            "window_count": window_count,
            "windows_covered": windows_covered,
            "window_coverage": (
                windows_covered / window_count if window_count else 0.0
            ),
        },
        "videos": [asdict(v) for v in videos],
    }

    if args.out:
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[sampling] JSON written to {args.out}")
    print(_markdown_report(report))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score overlay golden coverage under current keyframe sampling.",
    )
    parser.add_argument("--org-slug", default="devorg")
    parser.add_argument(
        "--org-id",
        default=None,
        help="Optional org UUID. If omitted, resolves --org-slug from Postgres.",
    )
    parser.add_argument(
        "--golden-dir",
        type=Path,
        required=True,
        help="Overlay golden directory or parent golden directory.",
    )
    parser.add_argument("--video-id", action="append", default=[])
    parser.add_argument("--max-keyframes", type=int, default=60)
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
