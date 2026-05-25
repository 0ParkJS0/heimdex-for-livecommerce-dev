"""Vision-LLM extraction of product info from overlay-bearing keyframes.

For each candidate frame the detector flagged ``has_overlay=True``,
ask gpt-4o-mini with a strict-JSON prompt for the list of products
visible on the overlay card. Responses parse into
:class:`ProductExtraction` rows.

A coarse per-UTC-day budget guard caps total OpenAI spend; once the
cap is reached calls raise :class:`OverlayBudgetExceededError`. The
counter is in-process so a multi-process deployment would need a
shared backend; documented at the call site for the next reader.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.modules.shorts_auto_product.enumerate_overlay.errors import (
    OverlayBudgetExceededError,
)
from app.modules.shorts_auto_product.enumerate_overlay.product_clusterer import (
    ProductExtraction,
)

logger = logging.getLogger(__name__)


PROMPT_VERSION = "v2"

_PROMPT_PATH = (
    Path(__file__).parent / "prompts" / f"extraction_{PROMPT_VERSION}.txt"
)

# gpt-4o-mini token pricing as of 2026-05.
_GPT4O_MINI_INPUT_USD_PER_TOKEN = 0.150 / 1_000_000
_GPT4O_MINI_OUTPUT_USD_PER_TOKEN = 0.600 / 1_000_000

# Fallback estimate used only when the API skips the usage block. A
# real call always returns one.
_FALLBACK_INPUT_TOKENS = 765
_FALLBACK_OUTPUT_TOKENS = 200

_VALID_POSITIONS = frozenset({
    "top-left", "top-center", "top-right",
    "middle-left", "middle-center", "middle-right",
    "bottom-left", "bottom-center", "bottom-right",
    "full-frame",
})


# Per-day USD tally keyed by ISO date in UTC. Single-process. A
# multi-process deployment will need redis or a small DB table for
# accurate accounting; do not assume this is process-shared.
_DAILY_USAGE_USD: dict[str, float] = {}
_BUDGET_LOCK = asyncio.Lock()


def _today_key() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


async def _check_and_charge_budget(
    *, cost_usd: float, daily_cap_usd: float
) -> None:
    """Add ``cost_usd`` to today's tally; raise if the cap is crossed."""
    async with _BUDGET_LOCK:
        key = _today_key()
        current = _DAILY_USAGE_USD.get(key, 0.0)
        if current + cost_usd > daily_cap_usd:
            raise OverlayBudgetExceededError(
                f"daily extraction budget exhausted "
                f"(cap=${daily_cap_usd:.2f}, "
                f"current=${current:.4f}, "
                f"this_call=${cost_usd:.4f})"
            )
        _DAILY_USAGE_USD[key] = current + cost_usd


def _load_prompt() -> str:
    if not _PROMPT_PATH.is_file():
        raise FileNotFoundError(
            f"extraction prompt missing at {_PROMPT_PATH}"
        )
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _encode_image_jpeg_base64(img_bgr: np.ndarray, *, quality: int = 85) -> str:
    ok, buf = cv2.imencode(
        ".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality]
    )
    if not ok:
        raise RuntimeError("cv2.imencode failed for keyframe")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _parse_response_text(text: str) -> list[dict[str, Any]]:
    """Pull the products list out of the LLM JSON, tolerating fences."""
    if not text:
        return []
    s = text.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl > 0:
            s = s[nl + 1:]
        if s.endswith("```"):
            s = s[:-3].strip()
    try:
        data = json.loads(s)
    except Exception:
        start = s.find("{")
        end = s.rfind("}")
        if not (0 <= start < end):
            return []
        try:
            data = json.loads(s[start:end + 1])
        except Exception:
            return []
    if not isinstance(data, dict):
        return []
    raw = data.get("products", [])
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict)]


def _coerce_price(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        m = re.search(r"\d{1,3}(?:,\d{3})+|\d{3,}", value.replace(" ", ""))
        if m:
            try:
                return int(m.group().replace(",", ""))
            except Exception:
                return None
    return None


def _coerce_position(value: Any) -> str | None:
    if isinstance(value, str) and value.strip() in _VALID_POSITIONS:
        return value.strip()
    return None


async def extract_products(
    *,
    openai_client: Any,
    scene_id: str,
    timestamp_ms: int,
    detector_score: float,
    img_bgr: np.ndarray,
    daily_cap_usd: float,
    model: str = "gpt-4o-mini",
) -> tuple[list[ProductExtraction], float]:
    """Call the vision LLM on one overlay-bearing keyframe.

    Args:
        openai_client: ``AsyncOpenAI`` (or compatible test fake).
        scene_id, timestamp_ms, detector_score: Echoed onto every
            returned :class:`ProductExtraction` row.
        img_bgr: Decoded keyframe to send to the LLM.
        daily_cap_usd: Spend cap for the current UTC day. The whole
            module shares a single tally.
        model: OpenAI chat-completions model id. Only ``gpt-4o-mini``
            is exercised today; the parameter is here so a future
            Qwen / gpt-4o swap can stay drop-in.

    Returns:
        ``(extractions, cost_usd)``. ``extractions`` is empty when the
        LLM returned ``products=[]`` -- the natural false-positive
        filter that the prompt asks for explicitly.

    Raises:
        OverlayBudgetExceededError: today's spend already crosses the
            cap; the call is still made and charged so subsequent
            scenes get a clear stop signal too.
    """
    prompt = _load_prompt()
    b64 = _encode_image_jpeg_base64(img_bgr)

    response = await openai_client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        response_format={"type": "json_object"},
        max_tokens=800,
    )
    text = response.choices[0].message.content or ""

    usage = getattr(response, "usage", None)
    in_tokens = int(getattr(usage, "prompt_tokens", _FALLBACK_INPUT_TOKENS))
    out_tokens = int(getattr(usage, "completion_tokens", _FALLBACK_OUTPUT_TOKENS))
    cost = (
        in_tokens * _GPT4O_MINI_INPUT_USD_PER_TOKEN
        + out_tokens * _GPT4O_MINI_OUTPUT_USD_PER_TOKEN
    )

    await _check_and_charge_budget(
        cost_usd=cost, daily_cap_usd=daily_cap_usd
    )

    products: list[ProductExtraction] = []
    for p in _parse_response_text(text):
        name = p.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        products.append(
            ProductExtraction(
                scene_id=scene_id,
                timestamp_ms=timestamp_ms,
                detector_score=detector_score,
                extracted_name=name.strip(),
                extracted_price=_coerce_price(p.get("price")),
                position=_coerce_position(p.get("position")),
            )
        )
    return products, cost
