"""Orchestrator for overlay-driven shorts assembly.

End-to-end for a single product:

1. Pick the product out of an :class:`OverlayEnumerationResult`.
2. Cluster its overlay appearances into per-segment cut windows.
3. Pull the video's STT segments and silence intervals from the
   injected source adapters.
4. Run the slot-assembler (HOOK / HERO / DEMO / CLOSE) to produce a
   :class:`ShortsAssembly`.

The assembly is a plan only -- ffmpeg rendering is delegated to a
downstream worker.

Loose-coupling: this module imports ONLY from :mod:`app.config`, the
sibling :mod:`shorts_auto_product.overlay_shorts.enumeration_result`,
and own-module symbols.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Protocol

from app.modules.shorts_auto_product.overlay_shorts.enumeration_result import (
    OverlayEnumerationResult,
    OverlayProduct,
)
from app.modules.shorts_auto_product.overlay_shorts.errors import (
    OverlayShortsProductMissingError,
    OverlayShortsSourceUnavailableError,
)

logger = logging.getLogger(__name__)


OVERLAY_SHORTS_VERSION = "overlay-shorts-v0.1"


DurationPreset = Literal[15, 30, 60, 90, 120]
ALLOWED_DURATIONS: tuple[DurationPreset, ...] = (15, 30, 60, 90, 120)


@dataclass(frozen=True)
class OverlaySegment:
    """One temporal window in which a product's overlay was visible.

    ``padded`` is True when this came from a single keyframe -- the
    window was widened to ``MIN_CLIP_S`` so a usable clip exists.
    """

    product_id: str
    video_drive_id: str
    segment_index: int
    n_keyframes_in_segment: int
    first_keyframe_ms: int
    last_keyframe_ms: int
    clip_start_s: float
    clip_end_s: float
    padded: bool
    scene_ids: tuple[str, ...]


@dataclass(frozen=True)
class SttSegment:
    """One transcript line with ``[start_s, end_s]`` boundaries."""

    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True)
class ShortsSlot:
    """One contiguous slice of the final clip."""

    # 'HOOK' | 'HERO' | 'DEMO' | 'DEMO_1' | 'DEMO_2' | 'DEMO_3' | 'CLOSE'.
    name: str
    start_s: float
    end_s: float
    text: str
    reason: str


@dataclass(frozen=True)
class ShortsAssembly:
    """Plan for one shorts clip; ffmpeg rendering happens elsewhere."""

    product_id: str
    video_drive_id: str
    # Caller-supplied locator -- usually an S3 URL or a local path.
    source_video_locator: str
    target_duration_s: DurationPreset
    actual_duration_s: float
    slots: tuple[ShortsSlot, ...]
    assembly_version: str = OVERLAY_SHORTS_VERSION


class SttLoader(Protocol):
    """Source for the video's transcript."""

    async def get_for_video(self, video_drive_id: str) -> list[SttSegment]: ...


class SilenceLoader(Protocol):
    """Source for the video's silence intervals.

    Each tuple is ``(silence_start_s, silence_end_s)``. The assembler
    snaps cut points to the midpoints of these intervals.
    """

    async def get_for_video(
        self, video_drive_id: str
    ) -> list[tuple[float, float]]: ...


async def run_overlay_shorts(
    *,
    product_id: str,
    enumeration_result: OverlayEnumerationResult,
    video_duration_s: float,
    source_video_locator: str,
    stt_loader: SttLoader,
    silence_loader: SilenceLoader,
    target_duration_s: DurationPreset = 60,
) -> ShortsAssembly:
    """Build a :class:`ShortsAssembly` for one product.

    Args:
        product_id: The product to assemble. Must exist in
            ``enumeration_result.products``.
        enumeration_result: Overlay enumeration output, hydrated from
            the persisted overlay-source catalog (the worker's overlay
            pass produces these rows).
        video_duration_s: Source video duration in seconds. Caller
            supplies this so the module does not need ffprobe.
        source_video_locator: Echoed onto the assembly so a downstream
            renderer knows where to read frames from.
        stt_loader: Injected adapter that returns the video's STT.
        silence_loader: Injected adapter that returns silence intervals.
        target_duration_s: One of 15 / 30 / 60 / 90 / 120 seconds.

    Returns:
        Assembled :class:`ShortsAssembly` with HOOK + HERO + DEMO(s) +
        CLOSE slots in narrative order.

    Raises:
        OverlayShortsProductMissingError: ``product_id`` not in the
            enumeration result.
        OverlayShortsSourceUnavailableError: STT loader returned no
            segments.
        ValueError: ``target_duration_s`` not one of the presets.
    """
    if target_duration_s not in ALLOWED_DURATIONS:
        raise ValueError(
            f"target_duration_s must be one of {ALLOWED_DURATIONS}, "
            f"got {target_duration_s}"
        )

    product: OverlayProduct | None = next(
        (p for p in enumeration_result.products if p.product_id == product_id),
        None,
    )
    if product is None:
        raise OverlayShortsProductMissingError(
            f"product {product_id} not found in enumeration_result "
            f"(video={enumeration_result.video_drive_id})"
        )

    from app.modules.shorts_auto_product.overlay_shorts import (
        segment as segment_mod,
        shorts_assembler,
    )

    segments = segment_mod.extract_overlay_segments(
        product=product,
        video_drive_id=enumeration_result.video_drive_id,
        video_duration_s=video_duration_s,
    )

    stt_segments = await stt_loader.get_for_video(
        enumeration_result.video_drive_id
    )
    if not stt_segments:
        raise OverlayShortsSourceUnavailableError(
            f"STT loader returned no segments for "
            f"{enumeration_result.video_drive_id}"
        )

    silences = await silence_loader.get_for_video(
        enumeration_result.video_drive_id
    )

    return shorts_assembler.assemble_shorts_plan(
        product=product,
        overlay_segments=segments,
        stt_segments=stt_segments,
        silences=silences,
        video_duration_s=video_duration_s,
        source_video_locator=source_video_locator,
        target_duration_s=target_duration_s,
    )
