"""Probe overlay detector recall against overlay goldens.

This diagnostic runs inside the product-enumerate-worker image so it uses
the same OpenCV detector code and worker S3/API settings as the deployed
Aircloud worker, without loading OWLv2, SigLIP2, or OpenAI.

Example on staging:

    docker compose --profile product-enum run --rm --no-deps \
      -e ENUMERATE_ALLOW_CPU=true \
      -v /opt/heimdex/dev-heimdex-for-livecommerce/services/api/tests/shorts_auto_product/eval/goldens/overlay:/goldens:ro \
      product-enumerate-worker sh -lc '\
        pip install --no-deps -e /opt/heimdex-media-pipelines >/tmp/pip.log 2>&1 && \
        python -m src.diagnostics.overlay_detector_probe \
          --org-id 4d20264c-c440-4d69-8613-7d7558ea386b \
          --golden-dir /goldens \
          --video-file-map /tmp/overlay_video_file_map.json \
          --max-keyframes 180 \
          --out /tmp/overlay_detector_probe_180.json'
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from heimdex_media_pipelines.product_enum.overlay_detector import (
    DEFAULT_SCORE_THRESHOLD,
    score_keyframe,
)
from heimdex_worker_sdk.s3 import S3Client
from PIL import Image

from src.settings import WorkerSettings


@dataclass(frozen=True)
class GoldenProduct:
    label_kr: str
    expected_windows_ms: list[tuple[int, int]]
    category_hint: str | None = None


@dataclass(frozen=True)
class GoldenVideo:
    video_id: str
    category: str
    expected_products: list[GoldenProduct]


@dataclass(frozen=True)
class FrameProbe:
    scene_id: str
    start_ms: int
    end_ms: int
    sample_ms: int
    downloaded: bool
    has_overlay: bool
    score: float | None
    gate: bool | None
    reason: str
    ocr_char_count: int
    signals: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class WindowProbe:
    start_ms: int
    end_ms: int
    sampled_count: int
    downloaded_count: int
    detector_pass_count: int
    max_score: float | None
    first_loss_stage: str
    sampled_scene_ids: list[str]
    detector_scene_ids: list[str]


@dataclass(frozen=True)
class ProductProbe:
    label_kr: str
    category_hint: str | None
    expected_window_count: int
    sampled_window_count: int
    detector_window_count: int
    first_loss_counts: dict[str, int]
    windows: list[WindowProbe]


@dataclass(frozen=True)
class VideoProbe:
    video_id: str
    file_id: str
    scene_count: int
    sampled_count: int
    downloaded_count: int
    detector_pass_count: int
    ocr_nonempty_count: int
    product_count: int
    window_count: int
    sampled_products: int
    detector_products: int
    sampled_windows: int
    detector_windows: int
    frames: list[FrameProbe]
    products: list[ProductProbe]


def _load_goldens(golden_dir: Path) -> list[GoldenVideo]:
    videos: list[GoldenVideo] = []
    for path in sorted(golden_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        products: list[GoldenProduct] = []
        for raw in data.get("expected_products", []):
            windows = [
                (int(start), int(end))
                for start, end in raw.get("expected_windows_ms", [])
                if int(end) > int(start)
            ]
            products.append(
                GoldenProduct(
                    label_kr=str(raw.get("label_kr") or ""),
                    expected_windows_ms=windows,
                    category_hint=raw.get("category_hint"),
                )
            )
        videos.append(
            GoldenVideo(
                video_id=str(data["video_id"]),
                category=str(data.get("category") or ""),
                expected_products=products,
            )
        )
    return videos


def _load_video_file_map(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("--video-file-map must be a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def _sample_scenes(raw_scenes: list[dict[str, Any]], max_keyframes: int) -> list[dict[str, Any]]:
    if max_keyframes <= 0:
        raise ValueError("--max-keyframes must be positive")
    if len(raw_scenes) > max_keyframes:
        stride = len(raw_scenes) / max_keyframes
        return [raw_scenes[int(i * stride)] for i in range(max_keyframes)]
    return list(raw_scenes)


def _scene_sample_ms(scene: dict[str, Any]) -> int:
    raw = scene.get("keyframe_timestamp_ms")
    if isinstance(raw, int) and raw > 0:
        return raw
    start = int(scene.get("start_ms") or 0)
    end = int(scene.get("end_ms") or start)
    return start + max(0, end - start) // 2


def _fetch_scenes(
    *,
    settings: WorkerSettings,
    org_id: str,
    file_id: str,
) -> list[dict[str, Any]]:
    base = settings.drive_api_base_url.rstrip("/")
    url = f"{base}/internal/videos/{file_id}/scenes-with-keyframes"
    headers = {
        "Authorization": f"Bearer {settings.drive_internal_api_key}",
        "X-Heimdex-Org-Id": org_id,
    }
    with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
        response = client.get(url, headers=headers)
    response.raise_for_status()
    scenes = response.json().get("scenes", [])
    if not isinstance(scenes, list):
        raise RuntimeError(f"unexpected scenes response for {file_id}")
    scenes.sort(key=lambda s: int(s.get("start_ms") or 0))
    return scenes


def _pil_to_bgr(image: Image.Image) -> Any:
    import numpy as np

    rgb = np.asarray(image.convert("RGB"))
    return rgb[:, :, ::-1].copy()


def _gate_from_signals(signals: dict[str, float]) -> bool:
    return signals.get("ocr_price", 0.0) >= 0.5 or signals.get("rect", 0.0) >= 0.5


def _reject_reason(*, score: float, gate: bool, threshold: float) -> str:
    if score >= threshold and gate:
        return "detector_pass"
    if score < threshold and not gate:
        return "score_below_threshold_and_structural_gate_failed"
    if score < threshold:
        return "score_below_threshold"
    return "structural_gate_failed"


def _probe_frames(
    *,
    scenes: list[dict[str, Any]],
    settings: WorkerSettings,
    max_keyframes: int,
    score_threshold: float,
) -> list[FrameProbe]:
    s3 = S3Client(bucket=settings.drive_s3_bucket)
    frames: list[FrameProbe] = []
    for scene in _sample_scenes(scenes, max_keyframes):
        scene_id = str(scene.get("scene_id") or "")
        s3_key = scene.get("keyframe_s3_key")
        start_ms = int(scene.get("start_ms") or 0)
        end_ms = int(scene.get("end_ms") or 0)
        sample_ms = _scene_sample_ms(scene)
        ocr_text = str(scene.get("ocr_text_raw") or "")
        if not scene_id or not s3_key:
            frames.append(
                FrameProbe(
                    scene_id=scene_id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    sample_ms=sample_ms,
                    downloaded=False,
                    has_overlay=False,
                    score=None,
                    gate=None,
                    reason="missing_scene_id_or_keyframe_s3_key",
                    ocr_char_count=len(ocr_text),
                )
            )
            continue
        raw = s3.get_object_bytes(str(s3_key))
        if raw is None:
            frames.append(
                FrameProbe(
                    scene_id=scene_id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    sample_ms=sample_ms,
                    downloaded=False,
                    has_overlay=False,
                    score=None,
                    gate=None,
                    reason="keyframe_download_failed",
                    ocr_char_count=len(ocr_text),
                )
            )
            continue
        try:
            image = Image.open(io.BytesIO(raw))
            image.load()
            reading = score_keyframe(
                scene_id=scene_id,
                img_bgr=_pil_to_bgr(image),
                ocr_text=ocr_text,
                score_threshold=score_threshold,
            )
        except Exception:
            frames.append(
                FrameProbe(
                    scene_id=scene_id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    sample_ms=sample_ms,
                    downloaded=False,
                    has_overlay=False,
                    score=None,
                    gate=None,
                    reason="keyframe_decode_or_detector_failed",
                    ocr_char_count=len(ocr_text),
                )
            )
            continue
        gate = _gate_from_signals(reading.signals)
        frames.append(
            FrameProbe(
                scene_id=scene_id,
                start_ms=start_ms,
                end_ms=end_ms,
                sample_ms=sample_ms,
                downloaded=True,
                has_overlay=reading.has_overlay,
                score=reading.score,
                gate=gate,
                reason=_reject_reason(
                    score=reading.score,
                    gate=gate,
                    threshold=score_threshold,
                ),
                ocr_char_count=len(ocr_text),
                signals=reading.signals,
            )
        )
    return frames


def _window_probe(
    *,
    start_ms: int,
    end_ms: int,
    frames: list[FrameProbe],
) -> WindowProbe:
    inside = [f for f in frames if start_ms <= f.sample_ms < end_ms]
    downloaded = [f for f in inside if f.downloaded]
    passed = [f for f in inside if f.has_overlay]
    if passed:
        first_loss_stage = "detector_pass"
    elif not inside:
        first_loss_stage = "sampling_miss"
    elif not downloaded:
        first_loss_stage = "keyframe_download_failed"
    else:
        reasons = {f.reason for f in downloaded}
        if reasons == {"structural_gate_failed"}:
            first_loss_stage = "structural_gate_failed"
        elif reasons == {"score_below_threshold"}:
            first_loss_stage = "score_below_threshold"
        elif reasons == {"score_below_threshold_and_structural_gate_failed"}:
            first_loss_stage = "score_below_threshold_and_structural_gate_failed"
        else:
            first_loss_stage = "mixed_detector_reject"
    scores = [f.score for f in downloaded if f.score is not None]
    return WindowProbe(
        start_ms=start_ms,
        end_ms=end_ms,
        sampled_count=len(inside),
        downloaded_count=len(downloaded),
        detector_pass_count=len(passed),
        max_score=max(scores) if scores else None,
        first_loss_stage=first_loss_stage,
        sampled_scene_ids=[f.scene_id for f in inside],
        detector_scene_ids=[f.scene_id for f in passed],
    )


def _product_probe(product: GoldenProduct, frames: list[FrameProbe]) -> ProductProbe:
    windows = [
        _window_probe(start_ms=start, end_ms=end, frames=frames)
        for start, end in product.expected_windows_ms
    ]
    counts: dict[str, int] = {}
    for window in windows:
        counts[window.first_loss_stage] = counts.get(window.first_loss_stage, 0) + 1
    return ProductProbe(
        label_kr=product.label_kr,
        category_hint=product.category_hint,
        expected_window_count=len(windows),
        sampled_window_count=sum(1 for w in windows if w.sampled_count > 0),
        detector_window_count=sum(1 for w in windows if w.detector_pass_count > 0),
        first_loss_counts=counts,
        windows=windows,
    )


def _render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Overlay detector probe — max_keyframes={result['max_keyframes']}",
        "",
        "## Aggregate",
        "",
        f"- sampled product ceiling: `{result['sampled_products']}/{result['product_count']}` = `{result['sampled_product_rate']:.3f}`",
        f"- detector product ceiling: `{result['detector_products']}/{result['product_count']}` = `{result['detector_product_rate']:.3f}`",
        f"- sampled window ceiling: `{result['sampled_windows']}/{result['window_count']}` = `{result['sampled_window_rate']:.3f}`",
        f"- detector window ceiling: `{result['detector_windows']}/{result['window_count']}` = `{result['detector_window_rate']:.3f}`",
        "",
        "## Per Video",
        "",
        "| video_id | sampled frames | detector pass frames | products detector-covered | windows detector-covered |",
        "|---|---:|---:|---:|---:|",
    ]
    for video in result["videos"]:
        lines.append(
            "| {video_id} | {sampled_count} | {detector_pass_count} | "
            "{detector_products}/{product_count} | {detector_windows}/{window_count} |".format(
                **video
            )
        )
    return "\n".join(lines)


def _run(args: argparse.Namespace) -> int:
    settings = WorkerSettings()
    file_map = _load_video_file_map(args.video_file_map)
    goldens = _load_goldens(args.golden_dir)
    if args.video_id:
        wanted = set(args.video_id)
        goldens = [g for g in goldens if g.video_id in wanted]
    if not goldens:
        print("[detector] no goldens matched", file=sys.stderr)
        return 2

    videos: list[VideoProbe] = []
    for golden in goldens:
        file_id = file_map.get(golden.video_id)
        if not file_id:
            raise RuntimeError(f"missing file UUID for {golden.video_id}")
        UUID(file_id)  # validate early
        scenes = _fetch_scenes(
            settings=settings,
            org_id=args.org_id,
            file_id=file_id,
        )
        frames = _probe_frames(
            scenes=scenes,
            settings=settings,
            max_keyframes=args.max_keyframes,
            score_threshold=args.score_threshold,
        )
        products = [_product_probe(product, frames) for product in golden.expected_products]
        videos.append(
            VideoProbe(
                video_id=golden.video_id,
                file_id=file_id,
                scene_count=len(scenes),
                sampled_count=len(frames),
                downloaded_count=sum(1 for f in frames if f.downloaded),
                detector_pass_count=sum(1 for f in frames if f.has_overlay),
                ocr_nonempty_count=sum(1 for f in frames if f.ocr_char_count > 0),
                product_count=len(products),
                window_count=sum(p.expected_window_count for p in products),
                sampled_products=sum(1 for p in products if p.sampled_window_count > 0),
                detector_products=sum(1 for p in products if p.detector_window_count > 0),
                sampled_windows=sum(p.sampled_window_count for p in products),
                detector_windows=sum(p.detector_window_count for p in products),
                frames=frames,
                products=products,
            )
        )

    product_count = sum(v.product_count for v in videos)
    sampled_products = sum(v.sampled_products for v in videos)
    detector_products = sum(v.detector_products for v in videos)
    window_count = sum(p.expected_window_count for v in videos for p in v.products)
    sampled_windows = sum(v.sampled_windows for v in videos)
    detector_windows = sum(v.detector_windows for v in videos)
    result = {
        "org_id": args.org_id,
        "max_keyframes": args.max_keyframes,
        "score_threshold": args.score_threshold,
        "product_count": product_count,
        "sampled_products": sampled_products,
        "detector_products": detector_products,
        "sampled_product_rate": sampled_products / product_count if product_count else 0.0,
        "detector_product_rate": detector_products / product_count if product_count else 0.0,
        "window_count": window_count,
        "sampled_windows": sampled_windows,
        "detector_windows": detector_windows,
        "sampled_window_rate": sampled_windows / window_count if window_count else 0.0,
        "detector_window_rate": detector_windows / window_count if window_count else 0.0,
        "videos": [asdict(v) for v in videos],
    }
    if args.out:
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[detector] JSON written to {args.out}", file=sys.stderr)
    print(_render_markdown(result))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe overlay detector recall against overlay goldens.",
    )
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--golden-dir", type=Path, required=True)
    parser.add_argument("--video-file-map", type=Path, required=True)
    parser.add_argument("--video-id", action="append", default=[])
    parser.add_argument("--max-keyframes", type=int, default=60)
    parser.add_argument("--score-threshold", type=float, default=DEFAULT_SCORE_THRESHOLD)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(_run(_parse_args()))


if __name__ == "__main__":
    main()
