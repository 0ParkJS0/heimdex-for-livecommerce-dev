"""Replay overlay name filtering against S4 extractor artifacts.

S5a diagnostic: consume ``overlay_extractor_probe`` JSON, apply the same
``is_promo_or_noise`` gate used by the production overlay pipeline, and
measure how much raw extraction yield survives before OWLv2/SigLIP2
clustering or API consolidation.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from heimdex_media_pipelines.product_enum.overlay_name_filter import (
    is_promo_or_noise,
)


@dataclass(frozen=True)
class LabelDecision:
    label: str
    scene_id: str
    sample_ms: int
    kept: bool
    reason: str | None


@dataclass(frozen=True)
class WindowFilterYield:
    start_ms: int
    end_ms: int
    raw_label_count: int
    kept_label_count: int
    kept_labels: list[str]
    dropped_labels: list[str]


@dataclass(frozen=True)
class ProductFilterYield:
    label_kr: str
    expected_window_count: int
    raw_window_count: int
    kept_window_count: int
    windows: list[WindowFilterYield]


@dataclass(frozen=True)
class VideoFilterReplay:
    video_id: str
    raw_mentions: int
    kept_mentions: int
    dropped_mentions: int
    raw_frames: int
    kept_frames: int
    products_with_raw_extractions: int
    products_with_kept_extractions: int
    windows_with_raw_extractions: int
    windows_with_kept_extractions: int
    drop_reasons: dict[str, int]
    top_raw_labels: list[tuple[str, int]]
    top_kept_labels: list[tuple[str, int]]
    top_dropped_labels: list[tuple[str, int]]
    products: list[ProductFilterYield]
    decisions: list[LabelDecision] = field(default_factory=list)


def _product_label_decisions(frame: dict[str, Any]) -> list[LabelDecision]:
    out: list[LabelDecision] = []
    for product in frame.get("products", []):
        label = str(product.get("label") or "").strip()
        dropped, reason = is_promo_or_noise(label)
        out.append(
            LabelDecision(
                label=label,
                scene_id=str(frame.get("scene_id") or ""),
                sample_ms=int(frame.get("sample_ms") or 0),
                kept=not dropped,
                reason=reason,
            )
        )
    return out


def _window_yield(
    *,
    window: dict[str, Any],
    decisions: list[LabelDecision],
) -> WindowFilterYield:
    start_ms = int(window["start_ms"])
    end_ms = int(window["end_ms"])
    inside = [
        decision for decision in decisions
        if start_ms <= decision.sample_ms < end_ms
    ]
    kept = [decision.label for decision in inside if decision.kept]
    dropped = [decision.label for decision in inside if not decision.kept]
    return WindowFilterYield(
        start_ms=start_ms,
        end_ms=end_ms,
        raw_label_count=len(inside),
        kept_label_count=len(kept),
        kept_labels=sorted(set(kept)),
        dropped_labels=sorted(set(dropped)),
    )


def _video_replay(video: dict[str, Any], *, include_decisions: bool) -> VideoFilterReplay:
    decisions: list[LabelDecision] = []
    raw_by_frame: set[str] = set()
    kept_by_frame: set[str] = set()
    drop_reasons: Counter[str] = Counter()
    raw_labels: Counter[str] = Counter()
    kept_labels: Counter[str] = Counter()
    dropped_labels: Counter[str] = Counter()

    for frame in video.get("frames", []):
        frame_decisions = _product_label_decisions(frame)
        if frame_decisions:
            raw_by_frame.add(str(frame.get("scene_id") or ""))
        if any(decision.kept for decision in frame_decisions):
            kept_by_frame.add(str(frame.get("scene_id") or ""))
        for decision in frame_decisions:
            decisions.append(decision)
            raw_labels[decision.label] += 1
            if decision.kept:
                kept_labels[decision.label] += 1
            else:
                dropped_labels[decision.label] += 1
                drop_reasons[decision.reason or "unknown"] += 1

    product_yields: list[ProductFilterYield] = []
    for product in video.get("products", []):
        windows = [
            _window_yield(window=window, decisions=decisions)
            for window in product.get("windows", [])
        ]
        product_yields.append(
            ProductFilterYield(
                label_kr=str(product.get("label_kr") or ""),
                expected_window_count=len(windows),
                raw_window_count=sum(
                    1 for window in windows if window.raw_label_count > 0
                ),
                kept_window_count=sum(
                    1 for window in windows if window.kept_label_count > 0
                ),
                windows=windows,
            )
        )

    return VideoFilterReplay(
        video_id=str(video["video_id"]),
        raw_mentions=sum(raw_labels.values()),
        kept_mentions=sum(kept_labels.values()),
        dropped_mentions=sum(dropped_labels.values()),
        raw_frames=len(raw_by_frame),
        kept_frames=len(kept_by_frame),
        products_with_raw_extractions=sum(
            1 for product in product_yields if product.raw_window_count > 0
        ),
        products_with_kept_extractions=sum(
            1 for product in product_yields if product.kept_window_count > 0
        ),
        windows_with_raw_extractions=sum(
            product.raw_window_count for product in product_yields
        ),
        windows_with_kept_extractions=sum(
            product.kept_window_count for product in product_yields
        ),
        drop_reasons=dict(drop_reasons),
        top_raw_labels=raw_labels.most_common(25),
        top_kept_labels=kept_labels.most_common(25),
        top_dropped_labels=dropped_labels.most_common(25),
        products=product_yields,
        decisions=decisions if include_decisions else [],
    )


def _render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Overlay Name-Filter Replay",
        "",
        f"source: `{result['source']}`",
        "",
        "## Aggregate",
        "",
        f"- raw mentions: `{result['raw_mentions']}`",
        f"- kept mentions: `{result['kept_mentions']}`",
        f"- dropped mentions: `{result['dropped_mentions']}`",
        f"- products with kept extractions: `{result['products_with_kept_extractions']}/{result['product_count']}` = `{result['product_kept_rate']:.3f}`",
        f"- windows with kept extractions: `{result['windows_with_kept_extractions']}/{result['window_count']}` = `{result['window_kept_rate']:.3f}`",
        f"- drop reasons: `{result['drop_reasons']}`",
        "",
        "## Per Video",
        "",
        "| video_id | raw mentions | kept | dropped | products kept | windows kept |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for video in result["videos"]:
        lines.append(
            f"| {video['video_id']} | {video['raw_mentions']} | "
            f"{video['kept_mentions']} | {video['dropped_mentions']} | "
            f"{video['products_with_kept_extractions']}/{len(video['products'])} | "
            f"{video['windows_with_kept_extractions']}/{sum(p['expected_window_count'] for p in video['products'])} |"
        )
    lines.extend(["", "## Top Kept Labels", ""])
    for label, count in result["top_kept_labels"][:20]:
        lines.append(f"- `{label}`: {count}")
    lines.extend(["", "## Top Dropped Labels", ""])
    for label, count in result["top_dropped_labels"][:20]:
        lines.append(f"- `{label}`: {count}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay overlay name filtering against S4 extractor JSON.",
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--include-decisions", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    videos = [
        _video_replay(video, include_decisions=args.include_decisions)
        for video in data.get("videos", [])
    ]
    raw_mentions = sum(video.raw_mentions for video in videos)
    kept_mentions = sum(video.kept_mentions for video in videos)
    dropped_mentions = sum(video.dropped_mentions for video in videos)
    product_count = sum(len(video.products) for video in videos)
    window_count = sum(
        product.expected_window_count
        for video in videos
        for product in video.products
    )
    drop_reasons: Counter[str] = Counter()
    raw_labels: Counter[str] = Counter()
    kept_labels: Counter[str] = Counter()
    dropped_labels: Counter[str] = Counter()
    for video in videos:
        drop_reasons.update(video.drop_reasons)
        raw_labels.update(dict(video.top_raw_labels))
        kept_labels.update(dict(video.top_kept_labels))
        dropped_labels.update(dict(video.top_dropped_labels))

    result = {
        "source": str(args.input),
        "raw_mentions": raw_mentions,
        "kept_mentions": kept_mentions,
        "dropped_mentions": dropped_mentions,
        "product_count": product_count,
        "window_count": window_count,
        "products_with_raw_extractions": sum(
            video.products_with_raw_extractions for video in videos
        ),
        "products_with_kept_extractions": sum(
            video.products_with_kept_extractions for video in videos
        ),
        "product_kept_rate": (
            sum(video.products_with_kept_extractions for video in videos)
            / product_count
            if product_count else 0.0
        ),
        "windows_with_raw_extractions": sum(
            video.windows_with_raw_extractions for video in videos
        ),
        "windows_with_kept_extractions": sum(
            video.windows_with_kept_extractions for video in videos
        ),
        "window_kept_rate": (
            sum(video.windows_with_kept_extractions for video in videos)
            / window_count
            if window_count else 0.0
        ),
        "drop_reasons": dict(drop_reasons),
        "top_raw_labels": raw_labels.most_common(50),
        "top_kept_labels": kept_labels.most_common(50),
        "top_dropped_labels": dropped_labels.most_common(50),
        "videos": [asdict(video) for video in videos],
    }
    if args.out:
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[name-filter] JSON written to {args.out}")
    print(_render_markdown(result))


if __name__ == "__main__":
    main()
