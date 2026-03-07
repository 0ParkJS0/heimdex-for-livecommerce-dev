"""Centralized MIME-type classification for the content pipeline.

Shared between API (via re-export at ``app.modules.content_type``) and
drive-worker (direct import from ``heimdex_worker_sdk.content_type``).

All MIME-type decisions must flow through these helpers — no scattered
``startswith("video/")`` checks elsewhere in the codebase.
"""

from __future__ import annotations

IMAGE_MIME_TYPES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
})

VIDEO_MIME_PREFIX: str = "video/"


def classify_mime(mime_type: str) -> str:
    """Classify a MIME type string as ``"video"``, ``"image"``, or ``"unknown"``.

    >>> classify_mime("video/mp4")
    'video'
    >>> classify_mime("image/jpeg")
    'image'
    >>> classify_mime("application/pdf")
    'unknown'
    """
    if mime_type in IMAGE_MIME_TYPES:
        return "image"
    if mime_type.startswith(VIDEO_MIME_PREFIX):
        return "video"
    return "unknown"


def is_supported_mime(mime_type: str) -> bool:
    """Return ``True`` if *mime_type* is a supported video or image type."""
    return classify_mime(mime_type) != "unknown"


def is_image(mime_type: str) -> bool:
    """Return ``True`` if *mime_type* is a supported image type."""
    return mime_type in IMAGE_MIME_TYPES


def is_video(mime_type: str) -> bool:
    """Return ``True`` if *mime_type* is any video type."""
    return mime_type.startswith(VIDEO_MIME_PREFIX)
