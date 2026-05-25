"""Unit tests for tangibility classifier (Hybrid LR + LLM routing)."""
from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
import numpy as np
from app.modules.tangibility.predictor import classify_tangibility
from unittest.mock import MagicMock

def _fake_bundle(p_intangible: float) -> dict:
    """deterministic LR stub. classes 순서는 실제와 동일."""
    pipe = MagicMock()
    pipe.predict_proba.return_value = np.array(
        [[p_intangible, 1.0 - p_intangible]]
    )
    return {
        "pipeline": pipe,
        "classes": ["intangible", "tangible"],
    }

@pytest.fixture
def settings_hybrid():
    return SimpleNamespace(
        tangibility_mode="hybrid",
        tangibility_classifier_version="v1",
        tangibility_lr_gap_threshold=0.15,
        tangibility_llm_model="gpt-4o-mini",
        tangibility_llm_timeout_s=5.0,
        openai_api_key="sk-test",
    )


@pytest.fixture
def settings_lr_only(settings_hybrid):
    settings_hybrid.tangibility_mode = "lr_only"
    return settings_hybrid

@pytest.fixture
def settings_llm_only(settings_hybrid):
    settings_hybrid.tangibility_mode = "llm_only"
    return settings_hybrid

@pytest.mark.asyncio
async def test_no_summary_returns_label(settings_hybrid):
    result = await classify_tangibility("", settings_hybrid)
    assert result["label"] == "no_summary"
    assert result["source"] == "skip"
    assert result["p_intangible"] is None

@pytest.mark.asyncio
async def test_no_summary_whitespace_only(settings_hybrid):
    result = await classify_tangibility("   \n  ", settings_hybrid)
    assert result["label"] == "no_summary"

@pytest.mark.asyncio
async def test_lr_high_confidence_no_llm(settings_hybrid, monkeypatch):
    """LR이 강한 confidence면 LLM 안 부름 (gap >= threshold)."""
    # p_intangible=0.05 → tangible 0.95, gap=0.45 >> 0.15
    monkeypatch.setattr(
        "app.modules.tangibility.predictor._load_bundle",
        lambda: _fake_bundle(p_intangible=0.05),
    )
    with patch(
        "app.modules.tangibility.predictor._llm_classify",
        new=AsyncMock(),
    ) as mock_llm:
        result = await classify_tangibility("any text", settings_hybrid)
        mock_llm.assert_not_called()
        assert result["source"] == "lr"
        assert result["label"] == "tangible"
        assert result["p_intangible"] == 0.05

@pytest.mark.asyncio
async def test_hybrid_low_confidence_routes_to_llm(settings_hybrid, monkeypatch):
    """LR borderline (gap < 0.15)면 LLM 호출."""
    # p_intangible=0.55 → gap=0.05 < 0.15
    monkeypatch.setattr(
        "app.modules.tangibility.predictor._load_bundle",
        lambda: _fake_bundle(p_intangible=0.55),
    )
    with patch(
        "app.modules.tangibility.predictor._llm_classify",
        new=AsyncMock(return_value="intangible"),
    ) as mock_llm:
        result = await classify_tangibility("any text", settings_hybrid)
        mock_llm.assert_called_once()
        assert result["source"] == "llm"
        assert result["label"] == "intangible"
        assert result["p_intangible"] == 0.55  # LR 결과는 보존

@pytest.mark.asyncio
async def test_lr_only_skips_llm(settings_lr_only, monkeypatch):
    monkeypatch.setattr(
        "app.modules.tangibility.predictor._load_bundle",
        lambda: _fake_bundle(p_intangible=0.55),  # borderline이라도 lr_only면 LLM 안 감
    )
    with patch(
        "app.modules.tangibility.predictor._llm_classify",
        new=AsyncMock(),
    ) as mock_llm:
        result = await classify_tangibility("any text", settings_lr_only)
        mock_llm.assert_not_called()
        assert result["source"] == "lr"
        assert result["mode"] == "lr_only"

@pytest.mark.asyncio
async def test_llm_only_skips_lr(settings_llm_only):
    summary = "여행 패키지를 소개합니다."
    with patch(
        "app.modules.tangibility.predictor._llm_classify",
        new=AsyncMock(return_value="intangible"),
    ) as mock_llm:
        result = await classify_tangibility(summary, settings_llm_only)
        mock_llm.assert_called_once()
        assert result["source"] == "llm"
        assert result["p_intangible"] is None  # LR 안 봤으니

@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_lr(settings_hybrid, monkeypatch):
    """LLM 실패 시 LR 결과로 fail-open."""
    monkeypatch.setattr(
        "app.modules.tangibility.predictor._load_bundle",
        lambda: _fake_bundle(p_intangible=0.55),  # borderline → LLM 가야 함
    )
    with patch(
        "app.modules.tangibility.predictor._llm_classify",
        new=AsyncMock(side_effect=Exception("timeout")),
    ) as mock_llm:
        result = await classify_tangibility("any text", settings_hybrid)
        mock_llm.assert_called_once()  # 한 번 시도는 함
        assert result["source"] == "lr_fallback"
        assert result["label"] == "intangible"  # 0.55 > 0.5 → intangible
        assert result["p_intangible"] == 0.55

