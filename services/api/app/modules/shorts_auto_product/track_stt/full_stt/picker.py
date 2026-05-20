"""Full-STT product explainer picker — one LLM call, no slot structure.

Calls gpt-4o-mini once per clip with the full timestamped transcript +
product context, asks it to freely pick 3-8 segments that explain the
product, and validates the response (OpenAI strict-mode JSON schema →
Pydantic → semantic constraints). Any defect at any layer falls back to a
positional plan that requires no external calls.

Coupling:
* Imports ``app.lib.whisper_transcribe.budget`` for the BudgetTracker
  protocol + InMemoryBudgetTracker (same location as the storyboard LLM
  picker — do NOT import from ``app.modules.shorts_auto.llm.budget``).
* Does NOT import storyboard/, chunk_scorer, mention_extractor,
  segment_assembler, clip_selector, or any other track_stt submodule.
* Picker NEVER raises out — any defect path logs structured and returns
  a FullSttClipPlan with fallback_used=True.

Cost shape (gpt-4o-mini):
* 300-scene cap → ~9,000 input tokens × $0.15/1M = $0.00135
* ~200 output tokens × $0.60/1M = $0.00012
* Per call: ~$0.0015 (reservation: $0.002 to absorb token variance).
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.lib.whisper_transcribe.budget import (
    BudgetExceededError as _BudgetExceededError,
)
from app.lib.whisper_transcribe.budget import BudgetTracker as _BudgetTracker
from app.logging_config import get_logger
from app.modules.shorts_auto_product.track_stt.full_stt.prompt import (
    PROMPT_VERSION as _MODULE_PROMPT_VERSION,
    _SYSTEM_PROMPT,
    build_user_prompt,
    select_scenes_for_prompt,
)
from app.modules.shorts_auto_product.track_stt.full_stt.schemas import (
    _RESPONSE_JSON_SCHEMA,
    FullSttClipResponse,
)
from app.modules.shorts_auto_product.track_stt.full_stt.types import (
    FullSttClipPlan,
    FullSttScene,
    FullSttSegment,
)

logger = get_logger(__name__)

# Reserved per call. Slightly above the typical $0.0015 to absorb
# token-count variance from longer Korean transcripts.
_RESERVATION_USD = 0.002

# gpt-4o-mini pricing (USD per 1M tokens).
_MODEL_PRICING_USD_PER_M: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}

# Positional anchors for the fallback plan (fractions of scene list length).
_FALLBACK_POSITIONS = (0.1, 0.35, 0.6, 0.85)

# Duration validation bounds (fractions of target_duration_ms).
_DURATION_LOWER_FRAC = 0.30
_DURATION_UPPER_FRAC = 2.00


def _cost_from_usage(response: Any, *, model: str) -> float:
    pricing = _MODEL_PRICING_USD_PER_M.get(model, _MODEL_PRICING_USD_PER_M["gpt-4o-mini"])
    usage = response.usage
    if usage is None:
        return _RESERVATION_USD
    input_cost = (usage.prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (usage.completion_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost


def _stable_seed(*, llm_label: str, prompt_version: str) -> int:
    """Deterministic 32-bit seed from (llm_label, prompt_version).

    Same product + same prompt version → same OpenAI seed → same picks
    across runs (modulo OpenAI checkpoint-level non-determinism).
    """
    key = f"{llm_label}|{prompt_version}".encode()
    return int.from_bytes(hashlib.sha1(key).digest()[:4], "big")


@dataclass
class FullSttExplainerPicker:
    """Pick product-explainer segments from the full video transcript.

    Stateless once instantiated — ``pick`` is the entry point.
    Picker NEVER raises out: every defect path falls back to positional.
    """

    openai_client: Any  # AsyncOpenAI — typed as Any to avoid SDK import at module load
    budget_tracker: _BudgetTracker
    model: str = "gpt-4o-mini"
    prompt_version: str = "v1"
    timeout_s: float = 15.0
    max_scenes: int = 300
    _reservation_usd: float = field(default=_RESERVATION_USD, init=False)

    async def pick(
        self,
        *,
        scenes: list[FullSttScene],
        target_duration_ms: int,
        llm_label: str,
        spoken_aliases: list[str],
        org_id: UUID | None = None,
    ) -> FullSttClipPlan:
        """Pick segments via the LLM. Falls back to positional on any defect.

        Picker NEVER raises out — Protocol contract guarantee. Every defect
        path logs structured and returns FullSttClipPlan(fallback_used=True).
        """
        # ── 0. PROMPT_VERSION drift check ──
        if self.prompt_version != _MODULE_PROMPT_VERSION:
            logger.warning(
                "full_stt_prompt_version_drift",
                env_version=self.prompt_version,
                module_version=_MODULE_PROMPT_VERSION,
                resolution="using module value at runtime",
            )

        # ── 1. Select scenes with temporal coverage ──
        active_scenes = select_scenes_for_prompt(scenes, max_scenes=self.max_scenes)

        if not active_scenes:
            logger.info("full_stt_pick_skipped", reason="empty_scenes")
            return self._positional_fallback(active_scenes, target_duration_ms)

        # ── 2. Budget reservation ──
        try:
            self.budget_tracker.check_and_reserve(self._reservation_usd)
        except _BudgetExceededError as exc:
            logger.info(
                "full_stt_pick_skipped",
                reason="budget_exceeded",
                error=str(exc),
            )
            return self._positional_fallback(active_scenes, target_duration_ms)

        # ── 3. Build prompt + call OpenAI ──
        user_prompt = build_user_prompt(
            scenes=active_scenes,
            target_duration_ms=target_duration_ms,
            llm_label=llm_label,
            spoken_aliases=spoken_aliases,
        )
        seed = _stable_seed(llm_label=llm_label, prompt_version=self.prompt_version)

        logger.info(
            "full_stt_pick_request",
            scene_count=len(active_scenes),
            scene_count_pre_cap=len(scenes),
            target_duration_ms=target_duration_ms,
            model=self.model,
            prompt_version=self.prompt_version,
        )

        try:
            response = await asyncio.wait_for(
                self.openai_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": _RESPONSE_JSON_SCHEMA,
                    },
                    temperature=0.0,
                    seed=seed,
                ),
                timeout=self.timeout_s,
            )
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
            # Catch-all so an unrecognised SDK exception class doesn't bypass
            # the fallback. Loud structured log is the diagnostic.
            self.budget_tracker.release_reservation(self._reservation_usd)
            logger.warning(
                "full_stt_pick_skipped",
                reason="api_failure",
                error_class=type(exc).__name__,
                error=str(exc)[:200],
            )
            return self._positional_fallback(active_scenes, target_duration_ms)

        # ── 4. Parse + validate ──
        try:
            content = response.choices[0].message.content
            clip_response = FullSttClipResponse.model_validate_json(content)
            self._validate(clip_response, active_scenes, target_duration_ms)
        except (ValidationError, ValueError, KeyError, AttributeError) as exc:
            self.budget_tracker.release_reservation(self._reservation_usd)
            logger.warning(
                "full_stt_pick_skipped",
                reason="validation_failed",
                error_class=type(exc).__name__,
                error=str(exc)[:300],
            )
            return self._positional_fallback(active_scenes, target_duration_ms)

        # ── 5. Record cost + build plan ──
        cost_usd = _cost_from_usage(response, model=self.model)
        self.budget_tracker.record(cost_usd)

        segments = [
            FullSttSegment(
                scene_id=active_scenes[pick.segment_index].scene_id,
                source_start_ms=active_scenes[pick.segment_index].start_ms,
                source_end_ms=active_scenes[pick.segment_index].end_ms,
                rationale=pick.rationale,
            )
            for pick in clip_response.segments
        ]
        total_duration_ms = sum(s.duration_ms for s in segments)

        logger.info(
            "full_stt_pick_response",
            cost_usd=cost_usd,
            segment_count=len(segments),
            total_duration_ms=total_duration_ms,
            target_duration_ms=target_duration_ms,
            global_rationale=(clip_response.global_rationale or "")[:200],
            prompt_version=self.prompt_version,
            full_stt_fallback_used=False,
        )

        return FullSttClipPlan(
            segments=segments,
            total_duration_ms=total_duration_ms,
            global_rationale=clip_response.global_rationale,
            fallback_used=False,
        )

    # ──────────────────────── private helpers ────────────────────────

    def _validate(
        self,
        response: FullSttClipResponse,
        scenes: list[FullSttScene],
        target_duration_ms: int,
    ) -> None:
        """Raise ValueError on any semantic violation.

        Called after Pydantic parsing passes, so basic type / uniqueness
        constraints are already satisfied. This layer checks context-dependent
        constraints that require the original scene list.
        """
        n = len(scenes)

        # 1. All indices in range
        for pick in response.segments:
            if pick.segment_index >= n:
                raise ValueError(
                    f"segment_index {pick.segment_index} out of range [0, {n})"
                )

        # 2. Timestamps match scene exactly (hallucination check — the LLM
        #    was given exact timestamps; any deviation is fabrication)
        for pick in response.segments:
            scene = scenes[pick.segment_index]
            if pick.start_ms != scene.start_ms or pick.end_ms != scene.end_ms:
                raise ValueError(
                    f"segment_index={pick.segment_index}: timestamps "
                    f"{pick.start_ms}-{pick.end_ms} do not match scene "
                    f"{scene.start_ms}-{scene.end_ms}"
                )

        # 3. Chronological order (segments must be in ascending start_ms order)
        for i in range(len(response.segments) - 1):
            curr_start = scenes[response.segments[i].segment_index].start_ms
            next_start = scenes[response.segments[i + 1].segment_index].start_ms
            if curr_start >= next_start:
                raise ValueError(
                    f"segments not in chronological order at position {i}: "
                    f"{curr_start} >= {next_start}"
                )

        # 4. No overlapping segments
        for i in range(len(response.segments) - 1):
            curr_end = scenes[response.segments[i].segment_index].end_ms
            next_start = scenes[response.segments[i + 1].segment_index].start_ms
            if curr_end > next_start:
                raise ValueError(
                    f"segments {i} and {i+1} overlap: end={curr_end} > start={next_start}"
                )

        # 5. Total duration within bounds
        total_ms = sum(
            scenes[pick.segment_index].end_ms - scenes[pick.segment_index].start_ms
            for pick in response.segments
        )
        lower = _DURATION_LOWER_FRAC * target_duration_ms
        upper = _DURATION_UPPER_FRAC * target_duration_ms
        if total_ms < lower or total_ms > upper:
            raise ValueError(
                f"total_duration_ms={total_ms} outside bounds "
                f"[{lower:.0f}, {upper:.0f}] for target={target_duration_ms}"
            )

    def _positional_fallback(
        self,
        scenes: list[FullSttScene],
        target_duration_ms: int,
    ) -> FullSttClipPlan:
        """Select 4 scenes at fixed positional anchors. No external calls.

        Always succeeds. Returns FullSttClipPlan(fallback_used=True).
        """
        if not scenes:
            return FullSttClipPlan(
                segments=[],
                total_duration_ms=0,
                global_rationale="positional fallback — no scenes available",
                fallback_used=True,
            )

        n = len(scenes)
        seen: set[int] = set()
        segments: list[FullSttSegment] = []

        for frac in _FALLBACK_POSITIONS:
            idx = min(int(frac * n), n - 1)
            # Advance past already-used indices (handles very small scene lists)
            while idx in seen and idx + 1 < n:
                idx += 1
            if idx in seen:
                continue
            seen.add(idx)
            sc = scenes[idx]
            segments.append(
                FullSttSegment(
                    scene_id=sc.scene_id,
                    source_start_ms=sc.start_ms,
                    source_end_ms=sc.end_ms,
                    rationale="positional fallback",
                )
            )

        segments.sort(key=lambda s: s.source_start_ms)
        total_ms = sum(s.duration_ms for s in segments)

        logger.info(
            "full_stt_pick_fallback",
            segment_count=len(segments),
            total_duration_ms=total_ms,
            full_stt_fallback_used=True,
        )

        return FullSttClipPlan(
            segments=segments,
            total_duration_ms=total_ms,
            global_rationale="positional fallback — LLM pick unavailable",
            fallback_used=True,
        )
