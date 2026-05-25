"""Load per-scene metadata from OpenSearch and keyframe images from S3.

Per-scene metadata (one row per scene): ``scene_id``,
``keyframe_timestamp_ms``, ``ocr_text_raw``, ``transcript_raw``.
This is the signal set the classical overlay detector needs without
re-running OCR.

Keyframe images are pulled lazily from S3 by ``{prefix}/{scene_id}.jpg``
so the entire video's keyframes never sit in memory at once.

Loose-coupling: imports ONLY ``opensearchpy`` (transitively),
``boto3`` (via the injected client), ``numpy``, ``cv2``,
:mod:`app.config`, and own-module symbols.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import cv2
import numpy as np

from app.modules.shorts_auto_product.enumerate_overlay.errors import (
    OverlayKeyframeUnavailableError,
)

logger = logging.getLogger(__name__)


# Defensive ceiling. The hardest livecommerce video we have is a few
# hours with scenes every 8-12s, well under 2000. 5000 is a guard,
# not a budget -- pagination would be the right fix beyond that.
_MAX_SCENES_PER_QUERY = 5000


@dataclass(frozen=True)
class SceneMetadata:
    """One scene's signals usable by the overlay detector."""

    scene_id: str
    keyframe_timestamp_ms: int
    # May be empty when OCR has not been run on this scene yet.
    ocr_text_raw: str
    # May be empty for silent / non-narrated scenes.
    transcript_raw: str


async def load_scene_metadata(
    *,
    os_client: Any,
    index_alias: str,
    org_id: UUID,
    video_drive_id: str,
) -> list[SceneMetadata]:
    """Fetch one row per scene from OpenSearch, sorted by keyframe ts.

    Filtered to scenes that have a ``keyframe_timestamp_ms`` -- i.e.,
    video scenes (image scenes have a different content_type and lack
    keyframe extraction).

    Raises:
        OverlayKeyframeUnavailableError: zero matching scenes found.
            This can mean the video has not been indexed yet or that
            its scenes lost their keyframe metadata.
    """
    response = await os_client.search(
        index=index_alias,
        body={
            "size": _MAX_SCENES_PER_QUERY,
            "query": {
                "bool": {
                    "must": [
                        {"term": {"org_id": str(org_id)}},
                        {"term": {"video_id": video_drive_id}},
                    ],
                    "filter": [
                        {"exists": {"field": "keyframe_timestamp_ms"}},
                    ],
                },
            },
            "_source": [
                "scene_id",
                "keyframe_timestamp_ms",
                "ocr_text_raw",
                "transcript_raw",
            ],
            "sort": [{"keyframe_timestamp_ms": "asc"}],
        },
    )

    hits = response.get("hits", {}).get("hits", []) or []
    out: list[SceneMetadata] = []
    for hit in hits:
        src = hit.get("_source", {}) or {}
        scene_id = src.get("scene_id")
        ts = src.get("keyframe_timestamp_ms")
        if not scene_id or ts is None:
            continue
        out.append(
            SceneMetadata(
                scene_id=str(scene_id),
                keyframe_timestamp_ms=int(ts),
                ocr_text_raw=str(src.get("ocr_text_raw") or ""),
                transcript_raw=str(src.get("transcript_raw") or ""),
            )
        )

    if not out:
        logger.info(
            "overlay_enum_no_scenes",
            extra={
                "video_id": video_drive_id,
                "org_id": str(org_id),
                "hit_count": len(hits),
            },
        )
        raise OverlayKeyframeUnavailableError(
            f"video {video_drive_id} has no scenes with keyframe_timestamp_ms "
            f"(scanned {len(hits)} rows)"
        )
    return out


def _parse_s3_url(url: str) -> tuple[str, str]:
    """Split ``s3://bucket/key/...`` into ``(bucket, key_prefix)``."""
    if not url.startswith("s3://"):
        raise ValueError(f"keyframe_s3_prefix must start with s3://: {url!r}")
    rest = url[len("s3://"):]
    bucket, _, key = rest.partition("/")
    if not bucket:
        raise ValueError(f"keyframe_s3_prefix has no bucket: {url!r}")
    return bucket, key


def download_keyframe(
    *,
    s3_client: Any,
    keyframe_s3_prefix: str,
    scene_id: str,
) -> np.ndarray:
    """Download ``{prefix}/{scene_id}.jpg`` from S3 and decode as BGR.

    Synchronous because ``boto3`` and ``cv2.imdecode`` are blocking
    IO/CPU. The pipeline runs many of these in a worker thread so the
    event loop stays free.

    Returns:
        An ``HxWx3`` ``uint8`` ``ndarray`` in BGR channel order.

    Raises:
        OverlayKeyframeUnavailableError: object missing or undecodable.
    """
    bucket, key_prefix = _parse_s3_url(keyframe_s3_prefix.rstrip("/"))
    object_key = (
        f"{key_prefix}/{scene_id}.jpg" if key_prefix else f"{scene_id}.jpg"
    )
    body = s3_client.get_object(Bucket=bucket, Key=object_key)["Body"].read()
    arr = np.frombuffer(body, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise OverlayKeyframeUnavailableError(
            f"failed to decode keyframe at s3://{bucket}/{object_key}"
        )
    return img
