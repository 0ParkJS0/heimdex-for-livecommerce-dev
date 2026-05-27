"""Probe overlay extractor yield for candidate detector gates.

S4 diagnostic: run the same overlay-reader prompt/model on frames selected
by an S3 candidate gate, then report parsed product yield before OWLv2,
SigLIP2, name filtering, clustering, or consolidation can hide failures.

This script spends OpenAI budget unless ``--dry-run`` is passed.
"""

from __future__ import annotations

import argparse
import io
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from heimdex_media_pipelines.product_enum.overlay_detector import (
    DEFAULT_SCORE_THRESHOLD,
    score_keyframe,
)
from heimdex_worker_sdk.s3 import S3Client
from PIL import Image

from src.diagnostics.overlay_detector_probe import (
    GoldenVideo,
    _fetch_scenes,
    _load_goldens,
    _load_video_file_map,
    _pil_to_bgr,
    _sample_scenes,
    _scene_sample_ms,
)
from src.diagnostics.overlay_gate_candidates import _candidate_pass, _rank_frame
from src.overlay_extractor import (
    OVERLAY_EXTRACTION_PROMPT_VERSION,
    _GPT4O_MINI_INPUT_USD_PER_TOKEN,
    _GPT4O_MINI_OUTPUT_USD_PER_TOKEN,
    _FALLBACK_INPUT_TOKENS,
    _FALLBACK_OUTPUT_TOKENS,
    _coerce_position,
    _coerce_price,
    _image_to_data_url,
    _load_prompt,
    _parse_response_text,
)
from src.settings import WorkerSettings


@dataclass(frozen=True)
class ExtractedProduct:
    label: str
    price: int | None
    position: str | None


@dataclass(frozen=True)
class ExtractorFrame:
    video_id: str
    scene_id: str
    start_ms: int
    end_ms: int
    sample_ms: int
    detector_score: float
    detector_signals: dict[str, float]
    raw_response_text: str
    parse_status: str
    products: list[ExtractedProduct]
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    error_class: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class WindowYield:
    start_ms: int
    end_ms: int
    candidate_frame_count: int
    extracted_frame_count: int
    extracted_labels: list[str]


@dataclass(frozen=True)
class ProductYield:
    label_kr: str
    expected_window_count: int
    candidate_window_count: int
    extracted_window_count: int
    windows: list[WindowYield]


@dataclass(frozen=True)
class VideoYield:
    video_id: str
    file_id: str
    sampled_count: int
    candidate_frame_count: int
    extracted_frame_count: int
    extracted_product_count: int
    cost_usd: float
    products_with_candidate_frames: int
    products_with_extractions: int
    windows_with_candidate_frames: int
    windows_with_extractions: int
    frames: list[ExtractorFrame]
    products: list[ProductYield]


def _json_parse_status(text: str, parsed: list[dict[str, Any]]) -> str:
    if not text.strip():
        return "raw_empty"
    stripped = text.strip()
    if parsed:
        return "parsed_nonempty"
    try:
        data = json.loads(stripped)
    except Exception:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if 0 <= start < end:
            try:
                json.loads(stripped[start:end + 1])
                return "parsed_empty"
            except Exception:
                return "malformed_json"
        return "malformed_json"
    if isinstance(data, dict) and data.get("products") == []:
        return "parsed_empty"
    return "parsed_empty"


def _call_overlay_extractor(
    *,
    client: Any,
    model: str,
    image: Image.Image,
) -> tuple[str, list[ExtractedProduct], str, float, int, int]:
    prompt = _load_prompt()
    data_url = _image_to_data_url(image)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": "high"},
                    },
                ],
            },
        ],
        response_format={"type": "json_object"},
        max_tokens=800,
    )
    text = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    prompt_tokens = int(getattr(usage, "prompt_tokens", _FALLBACK_INPUT_TOKENS))
    completion_tokens = int(
        getattr(usage, "completion_tokens", _FALLBACK_OUTPUT_TOKENS)
    )
    cost = (
        prompt_tokens * _GPT4O_MINI_INPUT_USD_PER_TOKEN
        + completion_tokens * _GPT4O_MINI_OUTPUT_USD_PER_TOKEN
    )
    parsed = _parse_response_text(text)
    products: list[ExtractedProduct] = []
    for raw in parsed:
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        products.append(
            ExtractedProduct(
                label=name.strip(),
                price=_coerce_price(raw.get("price")),
                position=_coerce_position(raw.get("position")),
            )
        )
    return (
        text,
        products,
        _json_parse_status(text, parsed),
        cost,
        prompt_tokens,
        completion_tokens,
    )


def _load_candidate_frames(
    *,
    settings: WorkerSettings,
    org_id: str,
    golden: GoldenVideo,
    file_id: str,
    max_keyframes: int,
    score_threshold: float,
    candidate: str,
    cap_per_video: int | None,
) -> list[tuple[dict[str, Any], Image.Image, float, dict[str, float]]]:
    scenes = _fetch_scenes(settings=settings, org_id=org_id, file_id=file_id)
    s3 = S3Client(bucket=settings.drive_s3_bucket)
    selected: list[tuple[dict[str, Any], Image.Image, float, dict[str, float]]] = []

    for scene in _sample_scenes(scenes, max_keyframes):
        s3_key = scene.get("keyframe_s3_key")
        scene_id = str(scene.get("scene_id") or "")
        if not s3_key or not scene_id:
            continue
        raw = s3.get_object_bytes(str(s3_key))
        if raw is None:
            continue
        try:
            image = Image.open(io.BytesIO(raw))
            image.load()
            reading = score_keyframe(
                scene_id=scene_id,
                img_bgr=_pil_to_bgr(image),
                ocr_text=str(scene.get("ocr_text_raw") or ""),
                score_threshold=score_threshold,
            )
        except Exception:
            continue
        frame = {
            "scene_id": scene_id,
            "start_ms": int(scene.get("start_ms") or 0),
            "end_ms": int(scene.get("end_ms") or 0),
            "sample_ms": _scene_sample_ms(scene),
            "score": reading.score,
            "signals": reading.signals,
            "has_overlay": reading.has_overlay,
            "ocr_char_count": len(str(scene.get("ocr_text_raw") or "")),
        }
        if _candidate_pass(frame, candidate):
            selected.append((frame, image, reading.score, reading.signals))

    if cap_per_video is not None and len(selected) > cap_per_video:
        selected = sorted(
            selected,
            key=lambda row: _rank_frame(row[0]),
            reverse=True,
        )[:cap_per_video]
    selected.sort(key=lambda row: int(row[0]["sample_ms"]))
    return selected


def _score_product_yield(
    *,
    golden: GoldenVideo,
    frames: list[ExtractorFrame],
) -> list[ProductYield]:
    product_yields: list[ProductYield] = []
    for product in golden.expected_products:
        windows: list[WindowYield] = []
        for start_ms, end_ms in product.expected_windows_ms:
            inside = [
                frame for frame in frames
                if start_ms <= frame.sample_ms < end_ms
            ]
            extracted = [frame for frame in inside if frame.products]
            labels = sorted({
                item.label
                for frame in extracted
                for item in frame.products
            })
            windows.append(
                WindowYield(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    candidate_frame_count=len(inside),
                    extracted_frame_count=len(extracted),
                    extracted_labels=labels,
                )
            )
        product_yields.append(
            ProductYield(
                label_kr=product.label_kr,
                expected_window_count=len(windows),
                candidate_window_count=sum(
                    1 for window in windows
                    if window.candidate_frame_count > 0
                ),
                extracted_window_count=sum(
                    1 for window in windows
                    if window.extracted_frame_count > 0
                ),
                windows=windows,
            )
        )
    return product_yields


def _render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Overlay extractor probe",
        "",
        f"candidate: `{result['candidate']}`",
        f"cap_per_video: `{result['cap_per_video']}`",
        f"dry_run: `{result['dry_run']}`",
        "",
        "## Aggregate",
        "",
        f"- candidate frames: `{result['candidate_frame_count']}`",
        f"- extracted frames: `{result['extracted_frame_count']}`",
        f"- extracted product mentions: `{result['extracted_product_count']}`",
        f"- products with extractions: `{result['products_with_extractions']}/{result['product_count']}` = `{result['product_extraction_rate']:.3f}`",
        f"- windows with extractions: `{result['windows_with_extractions']}/{result['window_count']}` = `{result['window_extraction_rate']:.3f}`",
        f"- cost_usd: `${result['cost_usd']:.4f}`",
        "",
        "## Per Video",
        "",
        "| video_id | candidate frames | extracted frames | products | windows | cost |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for video in result["videos"]:
        lines.append(
            f"| {video['video_id']} | {video['candidate_frame_count']} | "
            f"{video['extracted_frame_count']} | "
            f"{video['products_with_extractions']}/{len(video['products'])} | "
            f"{video['windows_with_extractions']}/{sum(p['expected_window_count'] for p in video['products'])} | "
            f"${video['cost_usd']:.4f} |"
        )
    return "\n".join(lines)


def _run(args: argparse.Namespace) -> int:
    settings = WorkerSettings()
    file_map = _load_video_file_map(args.video_file_map)
    goldens = _load_goldens(args.golden_dir)
    if args.video_id:
        wanted = set(args.video_id)
        goldens = [golden for golden in goldens if golden.video_id in wanted]
    if not goldens:
        raise RuntimeError("no goldens matched")

    client = None
    if not args.dry_run:
        from openai import OpenAI

        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required unless --dry-run is used")
        client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_sec,
            max_retries=settings.openai_max_retries,
        )

    videos: list[VideoYield] = []
    total_frames_seen = 0
    for golden in goldens:
        file_id = file_map.get(golden.video_id)
        if not file_id:
            raise RuntimeError(f"missing file UUID for {golden.video_id}")
        candidate_rows = _load_candidate_frames(
            settings=settings,
            org_id=args.org_id,
            golden=golden,
            file_id=file_id,
            max_keyframes=args.max_keyframes,
            score_threshold=args.score_threshold,
            candidate=args.candidate,
            cap_per_video=args.cap_per_video,
        )

        frame_results: list[ExtractorFrame] = []
        for frame, image, score, signals in candidate_rows:
            if (
                args.max_total_frames is not None
                and total_frames_seen >= args.max_total_frames
            ):
                break
            total_frames_seen += 1
            started = time.monotonic()
            if args.dry_run:
                frame_results.append(
                    ExtractorFrame(
                        video_id=golden.video_id,
                        scene_id=str(frame["scene_id"]),
                        start_ms=int(frame["start_ms"]),
                        end_ms=int(frame["end_ms"]),
                        sample_ms=int(frame["sample_ms"]),
                        detector_score=float(score),
                        detector_signals=dict(signals),
                        raw_response_text="",
                        parse_status="dry_run",
                        products=[],
                        cost_usd=0.0,
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=0,
                    )
                )
                continue
            try:
                assert client is not None
                (
                    text,
                    products,
                    parse_status,
                    cost,
                    prompt_tokens,
                    completion_tokens,
                ) = _call_overlay_extractor(
                    client=client,
                    model=settings.overlay_extraction_model,
                    image=image,
                )
                frame_results.append(
                    ExtractorFrame(
                        video_id=golden.video_id,
                        scene_id=str(frame["scene_id"]),
                        start_ms=int(frame["start_ms"]),
                        end_ms=int(frame["end_ms"]),
                        sample_ms=int(frame["sample_ms"]),
                        detector_score=float(score),
                        detector_signals=dict(signals),
                        raw_response_text=text,
                        parse_status=parse_status,
                        products=products,
                        cost_usd=cost,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        latency_ms=int((time.monotonic() - started) * 1000),
                    )
                )
            except Exception as exc:
                frame_results.append(
                    ExtractorFrame(
                        video_id=golden.video_id,
                        scene_id=str(frame["scene_id"]),
                        start_ms=int(frame["start_ms"]),
                        end_ms=int(frame["end_ms"]),
                        sample_ms=int(frame["sample_ms"]),
                        detector_score=float(score),
                        detector_signals=dict(signals),
                        raw_response_text="",
                        parse_status="api_error",
                        products=[],
                        cost_usd=0.0,
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        error_class=exc.__class__.__name__,
                        error_message=str(exc)[:1000],
                    )
                )

        products = _score_product_yield(golden=golden, frames=frame_results)
        videos.append(
            VideoYield(
                video_id=golden.video_id,
                file_id=file_id,
                sampled_count=min(args.max_keyframes, len(candidate_rows)),
                candidate_frame_count=len(candidate_rows),
                extracted_frame_count=sum(1 for f in frame_results if f.products),
                extracted_product_count=sum(len(f.products) for f in frame_results),
                cost_usd=sum(f.cost_usd for f in frame_results),
                products_with_candidate_frames=sum(
                    1 for p in products if p.candidate_window_count > 0
                ),
                products_with_extractions=sum(
                    1 for p in products if p.extracted_window_count > 0
                ),
                windows_with_candidate_frames=sum(
                    p.candidate_window_count for p in products
                ),
                windows_with_extractions=sum(
                    p.extracted_window_count for p in products
                ),
                frames=frame_results,
                products=products,
            )
        )

    product_count = sum(len(video.products) for video in videos)
    window_count = sum(
        product.expected_window_count
        for video in videos
        for product in video.products
    )
    result = {
        "org_id": args.org_id,
        "candidate": args.candidate,
        "cap_per_video": args.cap_per_video,
        "max_keyframes": args.max_keyframes,
        "max_total_frames": args.max_total_frames,
        "dry_run": args.dry_run,
        "model": settings.overlay_extraction_model,
        "prompt_version": OVERLAY_EXTRACTION_PROMPT_VERSION,
        "candidate_frame_count": sum(v.candidate_frame_count for v in videos),
        "extracted_frame_count": sum(v.extracted_frame_count for v in videos),
        "extracted_product_count": sum(v.extracted_product_count for v in videos),
        "product_count": product_count,
        "window_count": window_count,
        "products_with_candidate_frames": sum(
            v.products_with_candidate_frames for v in videos
        ),
        "products_with_extractions": sum(
            v.products_with_extractions for v in videos
        ),
        "windows_with_candidate_frames": sum(
            v.windows_with_candidate_frames for v in videos
        ),
        "windows_with_extractions": sum(
            v.windows_with_extractions for v in videos
        ),
        "product_extraction_rate": (
            sum(v.products_with_extractions for v in videos) / product_count
            if product_count else 0.0
        ),
        "window_extraction_rate": (
            sum(v.windows_with_extractions for v in videos) / window_count
            if window_count else 0.0
        ),
        "cost_usd": sum(v.cost_usd for v in videos),
        "videos": [asdict(video) for video in videos],
    }
    if args.out:
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[extractor] JSON written to {args.out}")
    print(_render_markdown(result))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe overlay extractor yield for candidate detector gates.",
    )
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--golden-dir", type=Path, required=True)
    parser.add_argument("--video-file-map", type=Path, required=True)
    parser.add_argument("--video-id", action="append", default=[])
    parser.add_argument("--max-keyframes", type=int, default=180)
    parser.add_argument("--score-threshold", type=float, default=DEFAULT_SCORE_THRESHOLD)
    parser.add_argument("--candidate", default="rect033")
    parser.add_argument("--cap-per-video", type=int, default=60)
    parser.add_argument("--max-total-frames", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(_run(_parse_args()))


if __name__ == "__main__":
    main()
