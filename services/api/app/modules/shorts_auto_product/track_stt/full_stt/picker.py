"""Full-STT product mention extractor + multi-short grouping picker.

Two entry points:

* ``pick`` — one gpt-4o-mini call. Extracts EVERY scene range where the
  product is mentioned. The LLM sees per-scene transcript lines grouped
  under chunk headers (chunk grouping is context only — output is
  per-scene). Returns a ``FullSttClipPlan`` whose ``segments`` are the
  actual mention regions, with no target-duration packing.

* ``pick_many`` — two gpt-4o-mini calls. Stage 1 reuses the EXACT same
  mention extraction as ``pick`` (so "what counts as a mention" lives in
  one place). Stage 2 hands the found regions to the model and asks it to
  group them into N meaningfully-different shorts; each short's mention
  scenes are then packed front-to-back to the target render window
  (mention scenes only — no padding with non-mention scenes). A short that
  cannot be built (or when extraction/grouping fails) degrades to a
  distinct positional cut so exactly N plans are always returned.

Coupling:
* Imports ``app.lib.whisper_transcribe.budget`` for the BudgetTracker
  protocol + InMemoryBudgetTracker (same location as the storyboard LLM
  picker — do NOT import from ``app.modules.shorts_auto.llm.budget``).
* Does NOT import storyboard/, chunk_scorer, mention_extractor,
  segment_assembler, clip_selector, or any other track_stt submodule.
* Picker NEVER raises out — any defect path logs structured and returns
  a FullSttClipPlan with fallback_used=True.
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
    build_grouping_user_prompt,
    build_mention_system_prompt,
    build_mention_user_prompt,
    group_consecutive_scenes,
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
    FullSttGroupingResponse,
    FullSttGroupingShort,
    FullSttMention,
    build_grouping_response_schema,
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

# Final render duration bounds (fractions of target_duration_ms).
_DURATION_LOWER_FRAC = 0.75
_DURATION_UPPER_FRAC = 4 / 3


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
class _MentionExtraction:
    """Result of stage-1 mention extraction, shared by ``pick`` (builds one
    plan) and ``pick_many`` (groups the regions into N shorts).

    ``mentions`` are validated (in range, chronological, non-overlapping)
    against ``active_scenes``. ``cost_usd`` is already recorded on the
    budget tracker by the time this is returned.
    """

    mentions: list[FullSttMention]
    active_scenes: list[FullSttScene]
    global_rationale: str
    cost_usd: float


@dataclass
class FullSttExplainerPicker:
    """Full-STT picker with two entry points.

    * ``pick`` — extract every scene range where the product is mentioned.
    * ``pick_many`` — produce N meaningfully-different chunk-picked shorts.

    Stateless once instantiated. Picker NEVER raises out: every defect path
    falls back to a positional plan.
    """

    openai_client: Any  # AsyncOpenAI — typed as Any to avoid SDK import at module load
    budget_tracker: _BudgetTracker
    model: str = "gpt-4o-mini"
    prompt_version: str = "v1"
    timeout_s: float = 15.0
    max_scenes: int = 300
    scene_group_size: int = 15
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
        """Extract every scene range where the product is mentioned.

        The LLM is shown per-scene transcript lines grouped under chunk
        headers (chunk grouping is context only — output is per-scene). The
        returned plan's ``segments`` are the actual mention regions, with no
        target-duration packing. ``target_duration_ms`` is preserved in the
        signature for caller compatibility and is only used by the positional
        fallback.

        Picker NEVER raises out — Protocol contract guarantee. Every defect
        path logs structured and returns FullSttClipPlan(fallback_used=True).
        """
        extraction, error = await self._run_mention_extraction(
            scenes=scenes,
            target_duration_ms=target_duration_ms,
            llm_label=llm_label,
            spoken_aliases=spoken_aliases,
        )
        if extraction is None:
            return self._empty_failure_plan(error or "mention_extraction_failed")

        plan = self._build_plan_from_mentions(
            extraction.mentions,
            extraction.active_scenes,
            extraction.global_rationale,
        )

        logger.info(
            "full_stt_pick_response",
            cost_usd=extraction.cost_usd,
            mention_count=len(extraction.mentions),
            segment_count=len(plan.segments),
            total_duration_ms=plan.total_duration_ms,
            target_duration_ms=target_duration_ms,
            global_rationale=(extraction.global_rationale or "")[:200],
            prompt_version=self.prompt_version,
            full_stt_fallback_used=False,
        )

        return plan

    async def _run_mention_extraction(
        self,
        *,
        scenes: list[FullSttScene],
        target_duration_ms: int,
        llm_label: str,
        spoken_aliases: list[str],
    ) -> tuple[_MentionExtraction | None, str | None]:
        """Stage-1 mention extraction shared by ``pick`` and ``pick_many``.

        One gpt call over the per-scene transcript (grouped under chunk
        headers for context). Handles scene capping, budget reservation,
        the API call, parse + ``_validate_mentions``, and cost recording.

        Returns ``(extraction, None)`` on success (budget already recorded)
        or ``(None, error_reason)`` on any defect (reservation released, a
        structured ``full_stt_pick_skipped`` log already emitted). Never
        raises — the picker contract.
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
            return None, "empty_scenes"

        # ── 1b. Group scenes for chunk-header context (scenes stay addressable) ──
        scene_groups = group_consecutive_scenes(
            active_scenes, group_size=self.scene_group_size,
        )

        # ── 2. Budget reservation ──
        try:
            self.budget_tracker.check_and_reserve(self._reservation_usd)
        except _BudgetExceededError as exc:
            logger.info(
                "full_stt_pick_skipped", reason="budget_exceeded", error=str(exc),
            )
            return None, f"budget_exceeded: {exc}"

        # ── 3. Build prompt + call OpenAI ──
        user_prompt = build_mention_user_prompt(
            scene_groups=scene_groups,
            llm_label=llm_label,
            spoken_aliases=spoken_aliases,
        )
        seed = _stable_seed(llm_label=llm_label, prompt_version=self.prompt_version)

        logger.info(
            "full_stt_pick_request",
            scene_count=len(active_scenes),
            chunk_count=len(scene_groups),
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
                        {"role": "system", "content": build_mention_system_prompt(llm_label)},
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
            # the failure path. Loud structured log is the diagnostic.
            self.budget_tracker.release_reservation(self._reservation_usd)
            logger.warning(
                "full_stt_pick_skipped",
                reason="api_failure",
                error_class=type(exc).__name__,
                error=str(exc)[:200],
            )
            return None, f"api_failure: {type(exc).__name__}: {str(exc)[:200]}"

        # ── 4. Parse + validate ──
        try:
            content = response.choices[0].message.content
            clip_response = FullSttClipResponse.model_validate_json(content)
            self._validate_mentions(clip_response, active_scenes)
        except (ValidationError, ValueError, KeyError, AttributeError) as exc:
            self.budget_tracker.release_reservation(self._reservation_usd)
            logger.warning(
                "full_stt_pick_skipped",
                reason="validation_failed",
                error_class=type(exc).__name__,
                error=str(exc)[:300],
            )
            return None, f"validation_failed: {type(exc).__name__}: {str(exc)[:200]}"

        # ── 5. Record cost ──
        cost_usd = _cost_from_usage(response, model=self.model)
        self.budget_tracker.record(cost_usd)

        return (
            _MentionExtraction(
                mentions=clip_response.mentions,
                active_scenes=active_scenes,
                global_rationale=clip_response.global_rationale,
                cost_usd=cost_usd,
            ),
            None,
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
        """Pick ``n`` distinct shorts in TWO LLM calls. NEVER raises.

        Stage 1 reuses ``_run_mention_extraction`` (identical to ``pick``) to
        find every product-mention region. Stage 2 (``_run_grouping``) asks
        the model to group those regions into ``n`` distinct shorts; each
        short's mention scenes are then packed front-to-back to the target
        duration (mention scenes only — no padding).

        Whole-call defects (timeout, budget, parse failure) at either stage,
        or zero mentions found, degrade to ``n`` distinct positional fallback
        plans. Per-short defects (out-of-range region index, duplicate of an
        already-accepted short, or no usable scenes) degrade only that short
        to a distinct positional cut — valid LLM shorts are preserved. Always
        returns exactly ``n`` plans.
        """
        if n <= 0:
            return []

        # ── 0. PROMPT_VERSION drift check (grouping prompt) ──
        if self.prompt_version != _MODULE_MULTI_PROMPT_VERSION:
            logger.warning(
                "full_stt_multi_prompt_version_drift",
                env_version=self.prompt_version,
                module_version=_MODULE_MULTI_PROMPT_VERSION,
                resolution="using module value at runtime",
            )

        # ── 1. Stage 1: mention extraction (shared with ``pick``) ──
        extraction, error = await self._run_mention_extraction(
            scenes=scenes,
            target_duration_ms=target_duration_ms,
            llm_label=llm_label,
            spoken_aliases=spoken_aliases,
        )
        active_scenes = (
            extraction.active_scenes
            if extraction is not None
            else select_scenes_for_prompt(scenes, max_scenes=self.max_scenes)
        )
        if extraction is None or not extraction.mentions:
            logger.info(
                "full_stt_multi_extraction_unusable",
                reason=error or "no_mentions",
                requested_shorts=n,
            )
            return self._positional_fallback_many(active_scenes, target_duration_ms, n)

        # ── 2. Stage 2: group the found regions into N shorts ──
        grouping, group_error = await self._run_grouping(
            extraction=extraction,
            target_duration_ms=target_duration_ms,
            llm_label=llm_label,
            n=n,
        )
        if grouping is None:
            logger.info(
                "full_stt_multi_grouping_failed",
                reason=group_error or "grouping_failed",
                requested_shorts=n,
            )
            return self._positional_fallback_many(active_scenes, target_duration_ms, n)

        # ── 3. Build N plans: per-short validate + distinctness dedup ──
        plans: list[FullSttClipPlan] = []
        seen_signatures: set[tuple[int, ...]] = set()
        fallback_cursor = 0
        llm_short_count = 0

        for i in range(n):
            short = grouping.shorts[i] if i < len(grouping.shorts) else None
            plan: FullSttClipPlan | None = None
            if short is not None:
                signature = tuple(sorted(set(short.region_indices)))
                try:
                    self._validate_grouping_short(short, extraction.mentions)
                    if signature in seen_signatures:
                        raise ValueError("duplicate short (identical region set)")
                    plan = self._build_plan_from_regions(
                        short,
                        extraction.mentions,
                        extraction.active_scenes,
                        target_duration_ms,
                    )
                    if plan.is_empty:
                        raise ValueError("no usable scenes after packing")
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
            cost_usd=extraction.cost_usd,
            mention_region_count=len(extraction.mentions),
            requested_shorts=n,
            llm_shorts=llm_short_count,
            fallback_shorts=n - llm_short_count,
            prompt_version=self.prompt_version,
        )
        return plans

    async def _run_grouping(
        self,
        *,
        extraction: _MentionExtraction,
        target_duration_ms: int,
        llm_label: str,
        n: int,
    ) -> tuple[FullSttGroupingResponse | None, str | None]:
        """Stage-2 grouping call: partition the stage-1 mention regions into
        ``n`` distinct shorts.

        Reserves + records its own budget (second call of the pair). Returns
        ``(grouping, None)`` on success or ``(None, error_reason)`` on any
        defect (reservation released). Never raises.
        """
        try:
            self.budget_tracker.check_and_reserve(self._reservation_usd)
        except _BudgetExceededError as exc:
            logger.info(
                "full_stt_pick_skipped", reason="budget_exceeded", error=str(exc),
            )
            return None, f"budget_exceeded: {exc}"

        regions = self._regions_for_prompt(extraction)
        user_prompt = build_grouping_user_prompt(
            regions=regions,
            target_duration_ms=target_duration_ms,
            n=n,
        )
        seed = _stable_seed(llm_label=llm_label, prompt_version=self.prompt_version)

        logger.info(
            "full_stt_multi_pick_request",
            mention_region_count=len(regions),
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
                        "json_schema": build_grouping_response_schema(n),
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
            return None, f"api_failure: {type(exc).__name__}: {str(exc)[:200]}"

        try:
            content = response.choices[0].message.content
            grouping = FullSttGroupingResponse.model_validate_json(content)
        except (ValidationError, ValueError, KeyError, AttributeError) as exc:
            self.budget_tracker.release_reservation(self._reservation_usd)
            logger.warning(
                "full_stt_pick_skipped",
                reason="validation_failed",
                error_class=type(exc).__name__,
                error=str(exc)[:300],
            )
            return None, f"validation_failed: {type(exc).__name__}: {str(exc)[:200]}"

        cost_usd = _cost_from_usage(response, model=self.model)
        self.budget_tracker.record(cost_usd)
        return grouping, None

    @staticmethod
    def _regions_for_prompt(
        extraction: _MentionExtraction,
    ) -> list[tuple[int, int, str, str]]:
        """Flatten the stage-1 mentions into ``(start_ms, end_ms, text,
        rationale)`` tuples for the grouping prompt.

        Index in the returned list == the ``region_indices`` value the
        grouping model returns. Text concatenates the covered scenes'
        transcript in chronological order.
        """
        scenes = extraction.active_scenes
        regions: list[tuple[int, int, str, str]] = []
        for mention in extraction.mentions:
            covered = scenes[mention.start_scene_idx : mention.end_scene_idx + 1]
            text = " ".join(s.text for s in covered if s.text).strip()
            regions.append(
                (
                    scenes[mention.start_scene_idx].start_ms,
                    scenes[mention.end_scene_idx].end_ms,
                    text,
                    mention.rationale,
                )
            )
        return regions

    # ──────────────────────── private helpers ────────────────────────

    @staticmethod
    def _empty_failure_plan(reason: str) -> FullSttClipPlan:
        """Empty plan returned by the mention-extraction path on failure.

        Unlike the multi-short ``pick_many`` path (which falls back to a
        positional cut), mention extraction returns nothing rather than
        fake mentions — positional time slices would be semantically
        wrong here. ``fallback_used=True`` still flags that the LLM pick
        was not used; ``error`` carries the reason for downstream display.
        """
        return FullSttClipPlan(
            segments=[],
            total_duration_ms=0,
            global_rationale="",
            fallback_used=True,
            error=reason,
        )

    def _validate_mentions(
        self,
        response: FullSttClipResponse,
        scenes: list[FullSttScene],
    ) -> None:
        """Raise ValueError on any semantic violation for the mention path.

        Each mention is a [start_scene_idx, end_scene_idx] inclusive range
        into the per-scene transcript shown to the LLM. Bound order
        (``end >= start``) is already enforced by Pydantic; this checks
        constraints that need the scene list as context.
        """
        n = len(scenes)

        for mention in response.mentions:
            if mention.start_scene_idx >= n or mention.end_scene_idx >= n:
                raise ValueError(
                    f"mention range [{mention.start_scene_idx}, "
                    f"{mention.end_scene_idx}] out of range [0, {n})"
                )

        # Regions must be chronological and non-overlapping by scene index.
        # Adjacent regions are allowed (gap of zero) — the LLM is asked to
        # split rather than merge across discontinuities, so [5,7] then [8,8]
        # is a legitimate "two regions touching".
        for i in range(len(response.mentions) - 1):
            curr_end = response.mentions[i].end_scene_idx
            next_start = response.mentions[i + 1].start_scene_idx
            if next_start <= curr_end:
                raise ValueError(
                    f"mentions not chronological/non-overlapping at position "
                    f"{i}: end={curr_end} >= next_start={next_start}"
                )

    def _build_plan_from_mentions(
        self,
        mentions: list[FullSttMention],
        scenes: list[FullSttScene],
        global_rationale: str,
    ) -> FullSttClipPlan:
        """Build a plan whose segments are the actual mention regions.

        Each mention [start, end] expands to one segment per covered scene
        (so durations remain accurate even when scenes have gaps). No
        target-duration packing — total duration is the sum of mention
        durations.
        """
        segments: list[FullSttSegment] = []
        for mention in mentions:
            for scene_idx in range(mention.start_scene_idx, mention.end_scene_idx + 1):
                scene = scenes[scene_idx]
                segments.append(
                    FullSttSegment(
                        scene_id=scene.scene_id,
                        source_start_ms=scene.start_ms,
                        source_end_ms=scene.end_ms,
                        rationale=mention.rationale,
                    )
                )

        total_duration_ms = sum(s.duration_ms for s in segments)
        return FullSttClipPlan(
            segments=segments,
            total_duration_ms=total_duration_ms,
            global_rationale=global_rationale,
            fallback_used=False,
        )

    @staticmethod
    def _validate_grouping_short(
        short: FullSttGroupingShort,
        mentions: list[FullSttMention],
    ) -> None:
        """Raise ValueError if a grouping short references an out-of-range
        region.

        Used by the multi-short ``pick_many`` stage-2 flow. ``region_indices``
        point into the stage-1 ``mentions`` list. Non-emptiness and
        per-short uniqueness are already enforced by Pydantic; chronological
        order and non-overlap are guaranteed for free because the stage-1
        mentions are themselves validated chronological + non-overlapping
        (see ``_validate_mentions``) and the builder sorts the indices.
        """
        m = len(mentions)
        for ri in short.region_indices:
            if ri >= m:
                raise ValueError(
                    f"region_index {ri} out of range [0, {m})"
                )

    def _build_plan_from_regions(
        self,
        short: FullSttGroupingShort,
        mentions: list[FullSttMention],
        scenes: list[FullSttScene],
        target_duration_ms: int,
    ) -> FullSttClipPlan:
        """Build a short's render plan from its assigned mention regions.

        Used by the multi-short ``pick_many`` stage-2 flow. Expands each
        referenced region to its covered scenes (chronological — indices are
        sorted, and stage-1 regions are non-overlapping) and packs those
        mention scenes front-to-back to the target duration. No padding with
        non-mention scenes: if the assigned regions are shorter than target,
        the short is simply shorter.
        """
        candidate_scenes: list[tuple[FullSttScene, str]] = []
        for ri in sorted(set(short.region_indices)):
            mention = mentions[ri]
            for scene_idx in range(mention.start_scene_idx, mention.end_scene_idx + 1):
                candidate_scenes.append((scenes[scene_idx], mention.rationale))

        segments = self._pack_source_scenes_to_target(
            candidate_scenes,
            target_duration_ms,
        )
        total_duration_ms = sum(s.duration_ms for s in segments)
        return FullSttClipPlan(
            segments=segments,
            total_duration_ms=total_duration_ms,
            global_rationale=short.global_rationale,
            fallback_used=False,
        )

    def _pack_source_scenes_to_target(
        self,
        scenes: list[tuple[FullSttScene, str]],
        target_duration_ms: int,
    ) -> list[FullSttSegment]:
        lower, upper = self._duration_bounds(target_duration_ms)
        segments: list[FullSttSegment] = []
        total_ms = 0

        for scene, rationale in scenes:
            if total_ms >= target_duration_ms and total_ms >= lower:
                break
            remaining_ms = upper - total_ms
            if remaining_ms <= 0:
                break

            scene_duration_ms = scene.end_ms - scene.start_ms
            if scene_duration_ms <= 0:
                continue

            if (
                scene_duration_ms <= remaining_ms
                and total_ms + scene_duration_ms <= target_duration_ms
            ):
                take_ms = scene_duration_ms
            else:
                needed_ms = max(0, target_duration_ms - total_ms)
                if total_ms < lower:
                    needed_ms = max(needed_ms, lower - total_ms)
                if needed_ms <= 0:
                    break
                take_ms = min(scene_duration_ms, remaining_ms, needed_ms)

            if take_ms <= 0:
                continue

            segments.append(
                FullSttSegment(
                    scene_id=scene.scene_id,
                    source_start_ms=scene.start_ms,
                    source_end_ms=scene.start_ms + take_ms,
                    rationale=rationale,
                )
            )
            total_ms += take_ms

        return segments

    @staticmethod
    def _duration_bounds(target_duration_ms: int) -> tuple[int, int]:
        lower = int(_DURATION_LOWER_FRAC * target_duration_ms)
        upper = int(_DURATION_UPPER_FRAC * target_duration_ms)
        return lower, upper

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
        selected_scenes: list[FullSttScene] = []

        for frac in positions:
            idx = min(int(frac * n), n - 1)
            # Advance past already-used indices (handles very small scene lists)
            while idx in seen and idx + 1 < n:
                idx += 1
            if idx in seen:
                continue
            seen.add(idx)
            sc = scenes[idx]
            selected_scenes.append(sc)

        selected_scenes.sort(key=lambda s: s.start_ms)
        packed = self._pack_source_scenes_to_target(
            [(scene, "positional fallback") for scene in selected_scenes],
            target_duration_ms,
        )
        total_ms = sum(s.duration_ms for s in packed)

        logger.info(
            "full_stt_pick_fallback",
            segment_count=len(packed),
            total_duration_ms=total_ms,
            full_stt_fallback_used=True,
        )

        return FullSttClipPlan(
            segments=packed,
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
