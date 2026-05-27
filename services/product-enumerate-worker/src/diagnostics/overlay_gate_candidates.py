"""Evaluate candidate overlay detector gates from a detector-probe JSON.

This is S3 of the overlay recall diagnostics. It does not fetch keyframes
or rerun OpenCV. It consumes ``overlay_detector_probe`` output and compares
recall/cost exposure for candidate gates before we touch production logic.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _candidate_pass(frame: dict[str, Any], name: str) -> bool:
    signals = frame.get("signals") or {}
    score = float(frame.get("score") or 0.0)
    if frame.get("has_overlay"):
        return True
    if name == "current":
        return False
    if name == "rect033":
        return float(signals.get("rect") or 0.0) >= (1.0 / 3.0)
    if name == "rect033_or_density025":
        return (
            float(signals.get("rect") or 0.0) >= (1.0 / 3.0)
            or float(signals.get("ocr_text_density") or 0.0) >= 0.25
        )
    if name == "rect033_or_density025_no_promo":
        return (
            float(signals.get("promo_penalty") or 0.0) < 0.5
            and (
                float(signals.get("rect") or 0.0) >= (1.0 / 3.0)
                or float(signals.get("ocr_text_density") or 0.0) >= 0.25
            )
        )
    if name == "density025_no_promo":
        return (
            float(signals.get("promo_penalty") or 0.0) < 0.5
            and float(signals.get("ocr_text_density") or 0.0) >= 0.25
        )
    if name == "score020_or_rect033_no_promo":
        return (
            float(signals.get("promo_penalty") or 0.0) < 0.5
            and (score >= 0.20 or float(signals.get("rect") or 0.0) >= (1.0 / 3.0))
        )
    raise ValueError(f"unknown candidate gate: {name}")


def _rank_frame(frame: dict[str, Any]) -> tuple[bool, float, float, float, int]:
    signals = frame.get("signals") or {}
    return (
        bool(frame.get("has_overlay")),
        float(frame.get("score") or -9.0),
        float(signals.get("rect") or 0.0),
        float(signals.get("ocr_text_density") or 0.0),
        int(frame.get("ocr_char_count") or 0),
    )


def _eval_candidate(
    data: dict[str, Any],
    *,
    name: str,
    cap_per_video: int | None,
) -> dict[str, Any]:
    product_count = 0
    window_count = 0
    product_hits = 0
    window_hits = 0
    extractor_frame_count = 0
    per_video: list[dict[str, Any]] = []

    for video in data["videos"]:
        frames = list(video["frames"])
        selected = [frame for frame in frames if _candidate_pass(frame, name)]
        selected_uncapped_count = len(selected)
        if cap_per_video is not None and len(selected) > cap_per_video:
            selected = sorted(selected, key=_rank_frame, reverse=True)[:cap_per_video]
        selected_ids = {frame["scene_id"] for frame in selected}
        extractor_frame_count += len(selected)

        video_product_count = 0
        video_window_count = 0
        video_product_hits = 0
        video_window_hits = 0
        for product in video["products"]:
            product_count += 1
            video_product_count += 1
            hit_product = False
            for window in product["windows"]:
                window_count += 1
                video_window_count += 1
                hit_window = any(
                    scene_id in selected_ids
                    for scene_id in window["sampled_scene_ids"]
                )
                if hit_window:
                    window_hits += 1
                    video_window_hits += 1
                    hit_product = True
            if hit_product:
                product_hits += 1
                video_product_hits += 1

        per_video.append({
            "video_id": video["video_id"],
            "candidate_frames_uncapped": selected_uncapped_count,
            "candidate_frames": len(selected),
            "product_hits": video_product_hits,
            "product_count": video_product_count,
            "window_hits": video_window_hits,
            "window_count": video_window_count,
        })

    return {
        "candidate": name,
        "cap_per_video": cap_per_video,
        "extractor_frame_count": extractor_frame_count,
        "product_hits": product_hits,
        "product_count": product_count,
        "product_rate": product_hits / product_count if product_count else 0.0,
        "window_hits": window_hits,
        "window_count": window_count,
        "window_rate": window_hits / window_count if window_count else 0.0,
        "per_video": per_video,
    }


def _render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Overlay gate candidates — source={result['source']}",
        "",
        f"max_keyframes: `{result['max_keyframes']}`",
        "",
        "| candidate | cap/video | extractor frames | products | windows |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in result["candidates"]:
        cap = "none" if row["cap_per_video"] is None else str(row["cap_per_video"])
        lines.append(
            f"| `{row['candidate']}` | {cap} | {row['extractor_frame_count']} | "
            f"{row['product_hits']}/{row['product_count']} (`{row['product_rate']:.3f}`) | "
            f"{row['window_hits']}/{row['window_count']} (`{row['window_rate']:.3f}`) |"
        )
    return "\n".join(lines)


def _parse_candidate(value: str) -> tuple[str, int | None]:
    if ":" not in value:
        return value, None
    name, cap_raw = value.rsplit(":", 1)
    if cap_raw in {"", "none", "null"}:
        return name, None
    return name, int(cap_raw)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate overlay detector candidate gates from probe JSON.",
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        help=(
            "Candidate gate, optionally with ':cap_per_video'. "
            "Example: rect033:60"
        ),
    )
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    candidates = args.candidate or [
        "current",
        "density025_no_promo",
        "rect033:60",
        "rect033",
        "rect033_or_density025:60",
        "rect033_or_density025_no_promo:60",
    ]
    result = {
        "source": str(args.input),
        "max_keyframes": data.get("max_keyframes"),
        "candidates": [
            _eval_candidate(data, name=name, cap_per_video=cap)
            for name, cap in (_parse_candidate(c) for c in candidates)
        ],
    }
    if args.out:
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[gate-candidates] JSON written to {args.out}")
    print(_render_markdown(result))


if __name__ == "__main__":
    main()
