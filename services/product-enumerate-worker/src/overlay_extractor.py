"""Worker-side :class:`OverlayExtractor` impl backed by gpt-4o-mini.

Conforms to
:class:`heimdex_media_pipelines.product_enum.OverlayExtractor` — the
overlay pass's caller-injected vision LLM that reads on-screen
info-overlay graphics (price cards, product callouts) off an
overlay-bearing keyframe and returns the products visible on the card.

Ported from the (now-deleted) in-API
``shorts_auto_product.enumerate_overlay.product_extractor`` +
``prompts/extraction_v2.txt``. Two adaptations for the worker:

* **Synchronous** — the worker dispatch path is sync (mirrors
  ``OpenAIVlmClient``), so this uses the blocking ``openai.OpenAI``
  client and a ``threading.Lock`` budget guard instead of the API's
  ``AsyncOpenAI`` + ``asyncio.Lock``.
* **Protocol shape** — the pipeline calls ``extract(*, scene_id,
  frame_idx, image, ocr_text)`` with a PIL image (not a cv2 BGR array)
  and expects an :class:`OverlayExtractionBatch`. We encode the PIL
  image to a JPEG data URL just like ``openai_vlm._image_to_data_url``.

A coarse per-UTC-day budget guard caps total overlay-extraction spend;
once the cap is reached calls raise :class:`OverlayBudgetExceededError`.
The counter is in-process so a multi-process deployment would need a
shared backend — documented here for the next reader. The worker runs
``drive_product_enumerate_concurrency=1`` so this is accurate today.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from heimdex_media_pipelines.product_enum import (
    OverlayExtraction,
    OverlayExtractionBatch,
)

if TYPE_CHECKING:  # pragma: no cover
    from PIL import Image

logger = logging.getLogger(__name__)


# Bumped in lockstep with ``prompts/overlay_extraction_v2.txt``.
OVERLAY_EXTRACTION_PROMPT_VERSION = "v2"

_PROMPT_PATH = (
    Path(__file__).parent
    / "prompts"
    / f"overlay_extraction_{OVERLAY_EXTRACTION_PROMPT_VERSION}.txt"
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


class OverlayBudgetExceededError(Exception):
    """Today's overlay-extraction spend already crosses the cap. The
    overlay pass catches this and stops further extraction calls; the
    already-extracted candidates still flow through the rest of the
    pipeline."""


def _load_prompt() -> str:
    if not _PROMPT_PATH.is_file():
        raise FileNotFoundError(
            f"overlay extraction prompt missing at {_PROMPT_PATH}"
        )
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _image_to_data_url(image: "Image.Image", *, quality: int = 85) -> str:
    """PIL → base64 JPEG data URL (mirrors ``openai_vlm._image_to_data_url``)."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


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


class OverlayProductExtractor:
    """Synchronous gpt-4o-mini overlay reader. Conforms to
    :class:`heimdex_media_pipelines.product_enum.OverlayExtractor`.

    Constructed once per worker boot. The OpenAI HTTP client is the
    same blocking client family ``OpenAIVlmClient`` uses; pass a
    pre-built client in for tests, or let it construct one from
    ``api_key``.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        openai_client: Any = None,
        model: str = "gpt-4o-mini",
        daily_cap_usd: float = 20.0,
        timeout_sec: float = 30.0,
        max_retries: int = 3,
        # Gates the OCR-text grounding hint in ``extract()``. Default True
        # mirrors the in-PR behavior. Worker passes
        # ``settings.overlay_extraction_ocr_hint_enabled`` so the prompt
        # change has a 1-env-flip rollback if it ever causes recall loss
        # on a corpus where PaddleOCR misses product names.
        ocr_hint_enabled: bool = True,
    ) -> None:
        if openai_client is not None:
            self._client = openai_client
        else:
            from openai import OpenAI

            if not api_key:
                raise ValueError("OPENAI_API_KEY is required")
            self._client = OpenAI(
                api_key=api_key,
                timeout=timeout_sec,
                max_retries=max_retries,
            )
        self.model = model
        self.daily_cap_usd = daily_cap_usd
        self.ocr_hint_enabled = ocr_hint_enabled
        # Per-UTC-day USD tally keyed by ISO date. Single-process;
        # the worker runs at concurrency=1 so this is accurate. A
        # multi-process deploy would need redis / a DB counter.
        self._daily_usage_usd: dict[str, float] = {}
        self._budget_lock = threading.Lock()

    def _check_and_charge_budget(self, *, cost_usd: float) -> None:
        with self._budget_lock:
            key = datetime.now(UTC).strftime("%Y-%m-%d")
            current = self._daily_usage_usd.get(key, 0.0)
            if current + cost_usd > self.daily_cap_usd:
                raise OverlayBudgetExceededError(
                    f"daily overlay extraction budget exhausted "
                    f"(cap=${self.daily_cap_usd:.2f}, "
                    f"current=${current:.4f}, "
                    f"this_call=${cost_usd:.4f})"
                )
            self._daily_usage_usd[key] = current + cost_usd

    def extract(
        self,
        *,
        scene_id: str,
        frame_idx: int,
        image: "Image.Image",
        ocr_text: str,
    ) -> OverlayExtractionBatch:
        """Read the overlay graphic on one keyframe.

        ``ocr_text`` (PaddleOCR output for this scene) is injected into
        the prompt as a grounding hint when available. The VLM still
        reads the image directly for layout / position, but the OCR
        snippet anchors product *labels* against the literal on-screen
        text — gpt-4o-mini otherwise tends to fabricate plausible-
        sounding product names ("OSULLOC 라면", "종가 아삭한 국물용
        김치") on stylized cards. Empty OCR is a legitimate state (the
        scene's OCR enrichment hasn't completed yet); we fall back to
        the original image-only prompt in that case so behavior matches
        legacy when OCR is unavailable.

        Returns the products visible on the card plus the call's USD
        cost. Raises :class:`OverlayBudgetExceededError` once today's
        spend crosses the cap so the pass stops extracting further
        frames.
        """
        prompt = _load_prompt()
        if self.ocr_hint_enabled and ocr_text and ocr_text.strip():
            # Cap to bound input tokens. 800 chars is well below a
            # single overlay card's typical OCR yield (~150-300 chars);
            # the cap exists for outlier scenes where OCR misclassifies
            # background text and the snippet would otherwise balloon.
            ocr_snippet = ocr_text.strip()[:800]
            prompt = (
                f"{prompt}\n\n"
                f"참고: 이 frame의 OCR 인식 결과는 다음과 같습니다.\n"
                f"```\n{ocr_snippet}\n```\n"
                f"product name은 OCR 텍스트에 실제로 등장하는 한글 "
                f"문자열을 그대로 사용하세요. OCR에 없는 product를 "
                f"추측해서 만들지 마세요."
            )
        data_url = _image_to_data_url(image)

        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "high"},
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
        out_tokens = int(
            getattr(usage, "completion_tokens", _FALLBACK_OUTPUT_TOKENS)
        )
        cost = (
            in_tokens * _GPT4O_MINI_INPUT_USD_PER_TOKEN
            + out_tokens * _GPT4O_MINI_OUTPUT_USD_PER_TOKEN
        )

        # Charge first so the next frame gets a clear stop signal too.
        self._check_and_charge_budget(cost_usd=cost)

        extractions: list[OverlayExtraction] = []
        for p in _parse_response_text(text):
            name = p.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            extractions.append(
                OverlayExtraction(
                    label=name.strip(),
                    price=_coerce_price(p.get("price")),
                    position=_coerce_position(p.get("position")),
                )
            )

        return OverlayExtractionBatch(
            extractions=extractions,
            cost_usd=cost,
            debug={
                "scene_id": scene_id,
                "frame_idx": frame_idx,
                "model": self.model,
                "prompt_version": OVERLAY_EXTRACTION_PROMPT_VERSION,
            },
        )
