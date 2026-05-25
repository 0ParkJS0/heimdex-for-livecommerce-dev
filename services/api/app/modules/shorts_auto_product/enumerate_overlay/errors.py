"""Exceptions raised by :mod:`enumerate_overlay`."""

from __future__ import annotations


class OverlayEnumerationError(Exception):
    """Base for all overlay-enumeration errors."""


class OverlayBudgetExceededError(OverlayEnumerationError):
    """Daily extraction-LLM spend exceeded the configured cap.

    Raised by :mod:`product_extractor` when the running tally for the
    current UTC day would exceed
    ``settings.overlay_extraction_daily_budget_usd``. Callers should
    treat this as a soft failure and retry on the next day's budget
    window.
    """


class OverlayKeyframeUnavailableError(OverlayEnumerationError):
    """Source keyframes for the requested video are missing in S3.

    Raised by :mod:`keyframe_loader` when ``drive_files.keyframe_s3_prefix``
    is unset or the prefix yields no objects. Indicates an upstream
    ingestion gap, not a code bug.
    """


class OverlayDetectorBackendError(OverlayEnumerationError):
    """An external backend used by the detector failed.

    Wraps OpenSearch / OCR / image-decode failures so callers can
    distinguish infrastructure errors from algorithmic ones.
    """
