"""Unit tests for the primary_catalog_match signal on chunk_scorer + ChunkScore.

Wave 2.3 (chunk-level LLM catalog match) — the chunk_scorer LLM makes a
semantic call on "is this chunk really about the primary catalog?".
Chunks below the threshold are rejected.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.shorts_auto_product.track_stt import chunk_scorer
from app.modules.shorts_auto_product.track_stt.models import (
    ChunkScore,
    MentionSegment,
    MentionedScene,
)


# ---------- ChunkScore model ----------


def test_chunk_score_has_primary_catalog_match_default():
    """ChunkScore has a primary_catalog_match field, default=1.0 (back-compat)."""
    s = ChunkScore(hook_score=0.7, has_cta=False, importance_score=0.8)
    assert s.primary_catalog_match == 1.0


def test_chunk_score_accepts_primary_catalog_match():
    """primary_catalog_match can be set explicitly."""
    s = ChunkScore(
        hook_score=0.7, has_cta=False, importance_score=0.8,
        primary_catalog_match=0.3,
    )
    assert s.primary_catalog_match == 0.3
