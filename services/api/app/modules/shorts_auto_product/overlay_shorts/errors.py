"""Exceptions raised by :mod:`overlay_shorts`."""

from __future__ import annotations


class OverlayShortsError(Exception):
    """Base for all overlay-shorts errors."""


class OverlayShortsSourceUnavailableError(OverlayShortsError):
    """A required source (STT, silence, video) could not be loaded.

    Raised by source adapters and by the orchestrator when their
    return value is empty.
    """


class OverlayShortsProductMissingError(OverlayShortsError):
    """The requested product id is not present in the enumeration result."""
