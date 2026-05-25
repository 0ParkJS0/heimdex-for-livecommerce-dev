"""Hybrid (LR + LLM routing) tangibility classifier.
- mode='hybrid'   — LR + LLM routing (default). gap < threshold이면 LLM
- mode='lr_only'  — only LR (external dependency 0, cost 0)
- mode='llm_only' — only LLM (skip LR)
if summary is None return 'no_summary' label.
"""

from __future__ import annotations

import sys
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
import joblib

from openai import AsyncOpenAI
from app.modules.tangibility.model import TextSelector, WeightedLR  # noqa: F401

from app.modules.tangibility import model as _tangibility_model_legacy

sys.modules.setdefault("tangibility_model", _tangibility_model_legacy)

logger = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).parent / "weights" / "v1.joblib"
_PROMPT_PATH = Path(__file__).parent / "llm_prompt.md"

TangibilityLabel = Literal["tangible", "intangible", "no_summary"]
TangibilitySource = Literal["lr", "llm", "lr_fallback", "skip"]

@lru_cache(maxsize=1)
def _load_bundle() -> dict[str, Any]:
    """lazy loading of joblib bundle. dict structure: {pipeline, classes, ...}"""
    return joblib.load(_MODEL_PATH)

@lru_cache(maxsize=1)
def _load_llm_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")
_openai_client: AsyncOpenAI | None = None

def _get_openai_client(api_key: str) -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=api_key)
    return _openai_client

async def _llm_classify(
    summary: str,
    *,
    client: AsyncOpenAI,
    model: str,
    timeout_s: float,
) -> TangibilityLabel:
    """classify with OpenAI gpt-4o-mini. fails with ValueError."""
    resp = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _load_llm_prompt()},
            {"role": "user", "content": summary},
        ],
        temperature=0,
        timeout=timeout_s,
    )
    content = resp.choices[0].message.content or "{}"
    parsed = json.loads(content)
    label = (parsed.get("label") or "").strip().lower()
    if label not in ("tangible", "intangible"):
        raise ValueError(f"unexpected LLM label: {label!r}")
    return label  # type: ignore[return-value]

async def classify_tangibility(summary: str, settings) -> dict[str, Any]:
    """Returns:
        {
          "label": "tangible" | "intangible" | "no_summary",
          "source": "lr" | "llm" | "lr_fallback" | "skip",
          "p_intangible": float | None,
          "model_version": str,
          "mode": str,
        }
    """
    mode = settings.tangibility_mode
    if not summary or not summary.strip():
        return {
            "label": "no_summary",
            "source": "skip",
            "p_intangible": None,
            "model_version": settings.tangibility_classifier_version,
            "mode": mode,
        }
    # LR step 
    p_int: float | None = None
    lr_label: TangibilityLabel | None = None
    if mode != "llm_only":
        bundle = _load_bundle()
        pipe = bundle["pipeline"]
        classes = bundle["classes"]
        int_idx = classes.index("intangible")
        proba = pipe.predict_proba([{"summary": summary}])[0]
        p_int = float(proba[int_idx])
        lr_label = classes[int(proba.argmax())]  # type: ignore[assignment]
    # mode=lr_only: return LR results directly, no LLM, no gap check
    if mode == "lr_only":
        return {
            "label": lr_label,
            "source": "lr",
            "p_intangible": p_int,
            "model_version": settings.tangibility_classifier_version,
            "mode": mode,
        }
    # mode=hybrid: gap check
    needs_llm = False
    if mode == "hybrid":
        assert p_int is not None
        gap = abs(p_int - 0.5)
        needs_llm = gap < settings.tangibility_lr_gap_threshold
    if mode == "llm_only":
        needs_llm = True
    if not needs_llm:
        return {
            "label": lr_label,
            "source": "lr",
            "p_intangible": p_int,
            "model_version": settings.tangibility_classifier_version,
            "mode": mode,
        }
    # LLM step
    try:
        client = _get_openai_client(settings.openai_api_key)
        llm_label = await _llm_classify(
            summary,
            client=client,
            model=settings.tangibility_llm_model,
            timeout_s=settings.tangibility_llm_timeout_s,
        )
        return {
            "label": llm_label,
            "source": "llm",
            "p_intangible": p_int,
            "model_version": settings.tangibility_classifier_version,
            "mode": mode,
        }
    except Exception as e:
        logger.warning(
            "tangibility_llm_failed lr_label=%s mode=%s error=%s",
            lr_label, mode, str(e),
        )
        # if LLM fails, fall back to LR result. if llm_only, then no LR -> no_summary.
        if lr_label is None:
            return {
                "label": "no_summary",
                "source": "lr_fallback",
                "p_intangible": None,
                "model_version": settings.tangibility_classifier_version,
                "mode": mode,
            }
        return {
            "label": lr_label,
            "source": "lr_fallback",
            "p_intangible": p_int,
            "model_version": settings.tangibility_classifier_version,
            "mode": mode,
        }