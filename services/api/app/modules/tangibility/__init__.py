"""Tangibility classifier — Hybrid LR + LLM routing for product scan gate."""
from app.modules.tangibility.predictor import (
    classify_tangibility,
    TangibilityLabel,
    TangibilitySource,
)
__all__ = ["classify_tangibility", "TangibilityLabel", "TangibilitySource"]