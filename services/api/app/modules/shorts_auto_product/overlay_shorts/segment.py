"""Group a product's overlay appearances into clip-sized segments.

The premise of the overlay-shorts path: while a product's overlay is
on screen the host is talking about that product. The window the
overlay covers IS the clip the wizard will assemble around.

Each product's :class:`OverlayAppearance` list is partitioned into
segments by temporal proximity. Single-keyframe segments get
widened to a minimum duration so a usable clip exists; multi-keyframe
segments get a small symmetric padding.

Pure module -- no IO, no model calls.
"""

from __future__ import annotations

import logging

from app.modules.shorts_auto_product.overlay_shorts.enumeration_result import (
    OverlayAppearance,
    OverlayProduct,
)
from app.modules.shorts_auto_product.overlay_shorts.service import (
    OverlaySegment,
)

logger = logging.getLogger(__name__)


# Appearances further apart than this are treated as separate segments.
# 90s comes from the workspace dataset where keyframes sit ~45s apart
# and an overlay re-appearance after a full keyframe gap is a new
# segment.
DEFAULT_KEYFRAME_GAP_MS = 90_000

# Symmetric padding around the first/last keyframe of a segment so
# that the overlay's actual visibility window (which we cannot know
# precisely) is covered.
DEFAULT_SEGMENT_PADDING_MS = 22_500

# Single-keyframe segments only have one sample. Assume the host
# spent ~30s on the product around that frame.
DEFAULT_MIN_CLIP_S = 30.0

# Hard ceiling -- avoid 10-min clips even on very long segments.
DEFAULT_MAX_CLIP_S = 120.0


def _cluster_appearances(
    appearances: tuple[OverlayAppearance, ...],
    gap_ms: int,
) -> list[list[OverlayAppearance]]:
    """Partition appearances by temporal proximity."""
    apps = sorted(appearances, key=lambda a: a.timestamp_ms)
    if not apps:
        return []
    segments: list[list[OverlayAppearance]] = [[apps[0]]]
    for a in apps[1:]:
        if a.timestamp_ms - segments[-1][-1].timestamp_ms <= gap_ms:
            segments[-1].append(a)
        else:
            segments.append([a])
    return segments


def _compute_clip_window(
    segment: list[OverlayAppearance],
    *,
    video_duration_s: float,
    padding_ms: int,
    min_clip_s: float,
    max_clip_s: float,
) -> tuple[float, float, bool]:
    """Return ``(start_s, end_s, padded_from_single)`` for one segment."""
    first_ts = segment[0].timestamp_ms
    last_ts = segment[-1].timestamp_ms
    padded_from_single = len(segment) == 1

    if padded_from_single:
        center_s = first_ts / 1000.0
        half = min_clip_s / 2.0
        start_s = max(0.0, center_s - half)
        end_s = min(video_duration_s, center_s + half)
    else:
        start_s = max(0.0, (first_ts - padding_ms) / 1000.0)
        end_s = min(video_duration_s, (last_ts + padding_ms) / 1000.0)

    if end_s - start_s > max_clip_s:
        mid = (start_s + end_s) / 2.0
        start_s = max(0.0, mid - max_clip_s / 2.0)
        end_s = min(video_duration_s, mid + max_clip_s / 2.0)

    return start_s, end_s, padded_from_single


def extract_overlay_segments(
    *,
    product: OverlayProduct,
    video_drive_id: str,
    video_duration_s: float,
    keyframe_gap_ms: int = DEFAULT_KEYFRAME_GAP_MS,
    segment_padding_ms: int = DEFAULT_SEGMENT_PADDING_MS,
    min_clip_s: float = DEFAULT_MIN_CLIP_S,
    max_clip_s: float = DEFAULT_MAX_CLIP_S,
) -> list[OverlaySegment]:
    """Cluster ``product.appearances`` into clip-sized segments.

    Args:
        product: The :class:`OverlayProduct` whose appearances to split.
        video_drive_id: Echoed onto every :class:`OverlaySegment`.
        video_duration_s: Caps the right edge of each window.
        keyframe_gap_ms: Maximum gap between consecutive appearances
            that still counts as the same segment.
        segment_padding_ms: Symmetric padding for multi-keyframe
            segments.
        min_clip_s: Minimum duration for single-keyframe segments.
        max_clip_s: Hard ceiling on segment duration.

    Returns:
        Segments in time order. Empty when the product has no
        appearances.
    """
    clusters = _cluster_appearances(product.appearances, keyframe_gap_ms)
    out: list[OverlaySegment] = []
    for idx, cluster in enumerate(clusters):
        start_s, end_s, padded = _compute_clip_window(
            cluster,
            video_duration_s=video_duration_s,
            padding_ms=segment_padding_ms,
            min_clip_s=min_clip_s,
            max_clip_s=max_clip_s,
        )
        out.append(
            OverlaySegment(
                product_id=product.product_id,
                video_drive_id=video_drive_id,
                segment_index=idx,
                n_keyframes_in_segment=len(cluster),
                first_keyframe_ms=cluster[0].timestamp_ms,
                last_keyframe_ms=cluster[-1].timestamp_ms,
                clip_start_s=round(start_s, 3),
                clip_end_s=round(end_s, 3),
                padded=padded,
                scene_ids=tuple(a.scene_id for a in cluster),
            )
        )
    return out
