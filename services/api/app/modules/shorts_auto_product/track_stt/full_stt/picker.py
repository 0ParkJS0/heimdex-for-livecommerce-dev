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
    _MULTI_SYSTEM_PROMPT,
    _SYSTEM_PROMPT,
    build_multi_user_prompt,
    build_user_prompt,
    select_scenes_for_prompt,
)
from app.modules.shorts_auto_product.track_stt.full_stt.prompt import (
    MULTI_PROMPT_VERSION as _MODULE_MULTI_PROMPT_VERSION,
)
from app.modules.shorts_auto_product.track_stt.full_stt.prompt import (
    PROMPT_VERSION as _MODULE_PROMPT_VERSION,
)
from app.modules.shorts_auto_product.track_stt.full_stt.schemas import (
    _RESPONSE_JSON_SCHEMA,
    FullSttClipResponse,
    FullSttMultiClipResponse,
    FullSttShort,
    build_multi_response_schema,
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

# Distinct positional anchor patterns for the multi-short fallback. When the
# shared LLM call fails (or returns duplicates), each short falls back to a
# different pattern so we never emit N identical positional clones. Patterns
# cycle if N exceeds the list length. Distinctness is best-effort for very
# short scene lists (you cannot draw N disjoint subsets from a handful of
# scenes); realistic inputs (hundreds of scenes) satisfy it trivially.
_FALLBACK_PATTERNS: tuple[tuple[float, ...], ...] = (
    (0.1, 0.35, 0.6, 0.85),    # spread (matches single-short default)
    (0.05, 0.2, 0.4, 0.55),    # early-weighted
    (0.45, 0.6, 0.75, 0.9),    # late-weighted
    (0.15, 0.4, 0.55, 0.8),    # centered
    (0.0, 0.3, 0.65, 0.95),    # wide
)

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
        except (TimeoutError, Exception) as exc:  # noqa: BLE001
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

    async def pick_many(
        self,
        *,
        scenes: list[FullSttScene],
        target_duration_ms: int,
        llm_label: str,
        spoken_aliases: list[str],
        n: int,
        org_id: UUID | None = None,
    ) -> list[FullSttClipPlan]:
        """Pick ``n`` distinct shorts in ONE LLM call. NEVER raises.

        Whole-call defects (timeout, budget, parse failure) degrade to ``n``
        distinct positional fallback plans. Per-short defects (out-of-range
        index, non-chronological, overlap, duration out of bounds, or a
        duplicate of an already-accepted short) degrade only that short to a
        distinct positional cut — valid LLM shorts are preserved. Always
        returns exactly ``n`` plans.
        """
        if n <= 0:
            return []

        # ── 0. PROMPT_VERSION drift check (multi prompt) ──
        if self.prompt_version != _MODULE_MULTI_PROMPT_VERSION:
            logger.warning(
                "full_stt_multi_prompt_version_drift",
                env_version=self.prompt_version,
                module_version=_MODULE_MULTI_PROMPT_VERSION,
                resolution="using module value at runtime",
            )

        # ── 1. Select scenes with temporal coverage ──
        active_scenes = select_scenes_for_prompt(scenes, max_scenes=self.max_scenes)
        if not active_scenes:
            logger.info("full_stt_pick_skipped", reason="empty_scenes")
            return self._positional_fallback_many(active_scenes, target_duration_ms, n)

        # ── 2. Budget reservation (one for the whole call) ──
        try:
            self.budget_tracker.check_and_reserve(self._reservation_usd)
        except _BudgetExceededError as exc:
            logger.info(
                "full_stt_pick_skipped", reason="budget_exceeded", error=str(exc),
            )
            return self._positional_fallback_many(active_scenes, target_duration_ms, n)

        # ── 3. Build prompt + call OpenAI once ──
        user_prompt = build_multi_user_prompt(
            scenes=active_scenes,
            target_duration_ms=target_duration_ms,
            llm_label=llm_label,
            spoken_aliases=spoken_aliases,
            n=n,
        )
        seed = _stable_seed(llm_label=llm_label, prompt_version=self.prompt_version)

        logger.info(
            "full_stt_multi_pick_request",
            scene_count=len(active_scenes),
            scene_count_pre_cap=len(scenes),
            target_duration_ms=target_duration_ms,
            requested_shorts=n,
            model=self.model,
            prompt_version=self.prompt_version,
        )

        try:
            response = await asyncio.wait_for(
                self.openai_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _MULTI_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": build_multi_response_schema(n),
                    },
                    temperature=0.0,
                    seed=seed,
                ),
                timeout=self.timeout_s,
            )
        except (TimeoutError, Exception) as exc:  # noqa: BLE001
            self.budget_tracker.release_reservation(self._reservation_usd)
            logger.warning(
                "full_stt_pick_skipped",
                reason="api_failure",
                error_class=type(exc).__name__,
                error=str(exc)[:200],
            )
            return self._positional_fallback_many(active_scenes, target_duration_ms, n)

        # ── 4. Parse top-level shape ──
        try:
            content = response.choices[0].message.content
            multi = FullSttMultiClipResponse.model_validate_json(content)
        except (ValidationError, ValueError, KeyError, AttributeError) as exc:
            self.budget_tracker.release_reservation(self._reservation_usd)
            logger.warning(
                "full_stt_pick_skipped",
                reason="validation_failed",
                error_class=type(exc).__name__,
                error=str(exc)[:300],
            )
            return self._positional_fallback_many(active_scenes, target_duration_ms, n)

        # ── 5. Record cost ──
        cost_usd = _cost_from_usage(response, model=self.model)
        self.budget_tracker.record(cost_usd)

        # ── 6. Build N plans: per-short validate + distinctness dedup ──
        plans: list[FullSttClipPlan] = []
        seen_signatures: set[tuple[int, ...]] = set()
        fallback_cursor = 0
        llm_short_count = 0

        for i in range(n):
            short = multi.shorts[i] if i < len(multi.shorts) else None
            plan: FullSttClipPlan | None = None
            if short is not None:
                signature = tuple(p.segment_index for p in short.segments)
                try:
                    self._validate(short, active_scenes, target_duration_ms)
                    if signature in seen_signatures:
                        raise ValueError("duplicate short (identical segment set)")
                    plan = self._build_plan_from_short(short, active_scenes)
                    seen_signatures.add(signature)
                    llm_short_count += 1
                except (ValueError, KeyError, IndexError):
                    plan = None
            if plan is None:
                pattern = _FALLBACK_PATTERNS[fallback_cursor % len(_FALLBACK_PATTERNS)]
                fallback_cursor += 1
                plan = self._positional_fallback(
                    active_scenes, target_duration_ms, positions=pattern,
                )
            plans.append(plan)

        logger.info(
            "full_stt_multi_pick_response",
            cost_usd=cost_usd,
            requested_shorts=n,
            llm_shorts=llm_short_count,
            fallback_shorts=n - llm_short_count,
            prompt_version=self.prompt_version,
        )
        return plans

    # ──────────────────────── private helpers ────────────────────────

    def _validate(
        self,
        response: FullSttClipResponse | FullSttShort,
        scenes: list[FullSttScene],
        target_duration_ms: int,
    ) -> None:
        """Raise ValueError on any semantic violation.

        Accepts either a single-short ``FullSttClipResponse`` or one
        ``FullSttShort`` from a multi-short response — both expose
        ``.segments``. Called after Pydantic parsing passes, so basic type /
        uniqueness constraints are already satisfied. This layer checks
        context-dependent constraints that require the original scene list.
        """
        n = len(scenes)

        # 1. All indices in range
        for pick in response.segments:
            if pick.segment_index >= n:
                raise ValueError(
                    f"segment_index {pick.segment_index} out of range [0, {n})"
                )

        # 2. Chronological order (segments must be in ascending start_ms order)
        for i in range(len(response.segments) - 1):
            curr_start = scenes[response.segments[i].segment_index].start_ms
            next_start = scenes[response.segments[i + 1].segment_index].start_ms
            if curr_start >= next_start:
                raise ValueError(
                    f"segments not in chronological order at position {i}: "
                    f"{curr_start} >= {next_start}"
                )

        # 3. No overlapping segments
        for i in range(len(response.segments) - 1):
            curr_end = scenes[response.segments[i].segment_index].end_ms
            next_start = scenes[response.segments[i + 1].segment_index].start_ms
            if curr_end > next_start:
                raise ValueError(
                    f"segments {i} and {i+1} overlap: end={curr_end} > start={next_start}"
                )

        # 4. Total duration within bounds
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

    def _build_plan_from_short(
        self,
        short: FullSttShort,
        scenes: list[FullSttScene],
    ) -> FullSttClipPlan:
        """Build a plan from one validated short. Call only after
        ``_validate`` passes (indices are guaranteed in range).
        """
        segments = [
            FullSttSegment(
                scene_id=scenes[pick.segment_index].scene_id,
                source_start_ms=scenes[pick.segment_index].start_ms,
                source_end_ms=scenes[pick.segment_index].end_ms,
                rationale=pick.rationale,
            )
            for pick in short.segments
        ]
        total_duration_ms = sum(s.duration_ms for s in segments)
        return FullSttClipPlan(
            segments=segments,
            total_duration_ms=total_duration_ms,
            global_rationale=short.global_rationale,
            fallback_used=False,
        )

    def _positional_fallback(
        self,
        scenes: list[FullSttScene],
        target_duration_ms: int,
        *,
        positions: tuple[float, ...] = _FALLBACK_POSITIONS,
    ) -> FullSttClipPlan:
        """Select scenes at fixed positional anchors. No external calls.

        Always succeeds. Returns FullSttClipPlan(fallback_used=True).
        ``positions`` lets the multi-short fallback vary the anchors per
        short so the N plans differ.
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

        for frac in positions:
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

    def _positional_fallback_many(
        self,
        scenes: list[FullSttScene],
        target_duration_ms: int,
        n: int,
    ) -> list[FullSttClipPlan]:
        """Produce ``n`` positional fallback plans using distinct anchor
        patterns so the N shorts differ. Best-effort distinctness for very
        short scene lists. Always returns exactly ``n`` plans.
        """
        plans: list[FullSttClipPlan] = []
        for i in range(n):
            pattern = _FALLBACK_PATTERNS[i % len(_FALLBACK_PATTERNS)]
            plans.append(
                self._positional_fallback(
                    scenes, target_duration_ms, positions=pattern
                )
            )
        return plans
