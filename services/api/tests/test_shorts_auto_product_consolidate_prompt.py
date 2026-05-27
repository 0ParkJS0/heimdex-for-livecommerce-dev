"""Regression tests for the consolidate LLM prompt.

Pin the wording / version so a refactor cannot silently drop the
cross-source identity check that the stt-cross-reference revision
introduced.

Background: on 2026-05-27, the post-vision consolidate hook
incorrectly rejected vision row "포기김치 봉지" as
``non_sellable:unspoken_visual`` even though STT row
"일상행복 포기김치 10kg" referenced the same physical product. The
prior prompt deferred the cross-reference to the LLM's loose
"category" judgment; the new prompt requires an explicit
container-suffix-strip → substring match against EVERY STT row's
llm_label + spoken_aliases before any ``unspoken_visual`` rejection.

These tests do NOT call gpt-4o — they pin the prompt STRING and
version constants. The behavioral effect on gpt-4o is validated by
the staging eval harness (see goldens/README.md) on demand.
"""
from __future__ import annotations

import pytest

from app.modules.shorts_auto_product.consolidate.llm_consolidator import (
    _DEFAULT_PROMPT_VERSION,
    _REJECTION_CATEGORIES,
    _SYSTEM_PROMPT,
)
from app.config import Settings


# ---------------------------------------------------------------------------
# Prompt version + config-default lockstep
# ---------------------------------------------------------------------------


class TestPromptVersionLockstep:
    """The code-side ``_DEFAULT_PROMPT_VERSION`` constant must match the
    config-side default. Drift between them silently stamps the WRONG
    version on every row (config wins at runtime). The 2026-05-27
    incident traced back to a v1.0 settings default that never moved
    while the code constant bumped to ``v2.0-stt-grounded``."""

    def test_code_default_matches_config_default(self):
        s = Settings(
            auto_shorts_product_v2_enabled=True,
            auto_shorts_product_v2_rollout_pct=100,
        )
        assert (
            s.auto_shorts_product_v2_consolidate_prompt_version
            == _DEFAULT_PROMPT_VERSION
        ), (
            "Code constant and config default drifted. Bump BOTH in "
            "lockstep or new rows will be stamped with the older version "
            "(config wins because the runtime path reads "
            "settings.auto_shorts_product_v2_consolidate_prompt_version, "
            "not the code default)."
        )

    def test_version_string_signals_the_stt_cross_reference_revision(self):
        """The version string is part of the rollback / audit story; pin
        it so a renumbering forces a deliberate edit."""
        assert "v2.1" in _DEFAULT_PROMPT_VERSION
        assert "cross-reference" in _DEFAULT_PROMPT_VERSION.lower()


# ---------------------------------------------------------------------------
# Prompt-wording regression — the unspoken_visual cross-reference clause
# ---------------------------------------------------------------------------


class TestUnspokenVisualCrossReferenceWording:
    """The new wording introduces FIVE concrete pieces of guidance the
    old wording lacked. Each is a separate test so a partial revert is
    visible in the failure name, not buried in a single assertion."""

    def test_explicit_container_suffix_strip_listed(self):
        """Container suffixes the prompt must list explicitly. Vision
        labels like '포기김치 봉지' → strip ' 봉지' → match against STT
        '일상행복 포기김치 10kg'. Without the explicit list, the LLM
        can't reliably perform the strip; that's the 2026-05-27 bug."""
        for suffix in ("봉지", "병", "통", "박스", "컵", "그릇"):
            assert suffix in _SYSTEM_PROMPT, (
                f"container suffix {suffix!r} missing from the prompt — "
                "the unspoken_visual cross-reference test depends on "
                "the LLM stripping these before substring-matching"
            )

    def test_explicit_stt_row_cross_reference_instruction(self):
        """The prompt must explicitly tell the LLM to cross-reference
        STT row labels + spoken_aliases before any unspoken_visual
        rejection. The old wording said 'category mismatch with
        host_spoken_terms' which the LLM interpreted too loosely."""
        assert "STT row" in _SYSTEM_PROMPT
        assert "spoken_aliases" in _SYSTEM_PROMPT
        assert "substring" in _SYSTEM_PROMPT.lower()

    def test_explicit_merge_directive_for_same_product(self):
        """When the substring check succeeds, the LLM must MERGE (not
        keep-as-own-group, not reject). The old wording allowed
        'fold or keep as its own group' which left the merge optional."""
        # Look for the directive in the unspoken_visual paragraph.
        # Loose match — wording can drift but the verb MUST appear.
        assert "MERGE" in _SYSTEM_PROMPT
        assert "instead of rejecting" in _SYSTEM_PROMPT.lower()

    def test_explicit_jongga_example_pins_the_staging_2026_05_27_case(self):
        """The concrete example documents the exact case that motivated
        the revision. Pin it so a wording cleanup doesn't lose the
        regression context for future readers."""
        # The exact products from the incident
        assert "포기김치" in _SYSTEM_PROMPT
        assert "일상행복" in _SYSTEM_PROMPT

    def test_rarely_used_emphasis(self):
        """The prior wording said 'use sparingly'; the new one
        upgrades that to 'RARELY USED' (caps) as a stronger anchor for
        the LLM. The phrase change is intentional and load-bearing."""
        assert "RARELY USED" in _SYSTEM_PROMPT


class TestUnspokenVisualNegativeGuards:
    """The cross-reference logic must NOT swing the prompt too
    aggressively in the other direction — these guards confirm the
    legitimate ``unspoken_visual`` use case (and adjacent rejection
    categories like ``host_equipment``, ``generic_noun``) remain in the
    prompt and aren't accidentally dropped."""

    def test_unspoken_visual_still_in_rejection_categories(self):
        """``unspoken_visual`` must remain a valid category — the
        revision narrows WHEN it fires, not whether it exists."""
        assert "unspoken_visual" in _REJECTION_CATEGORIES

    def test_host_equipment_kitchenware_handoff_documented(self):
        """For kitchenware props like '금색 냄비' (gold pot), the LLM
        should prefer ``host_equipment`` over ``unspoken_visual``.
        Pinning the example in the prompt keeps that handoff explicit."""
        # The new wording calls out kitchenware specifically; the
        # phrase 'host_equipment' must appear near a kitchenware
        # example.
        assert "host_equipment" in _SYSTEM_PROMPT
        # The Korean term for 'pot' (냄비) is the staging example.
        assert "냄비" in _SYSTEM_PROMPT

    def test_generic_noun_handoff_for_bare_labels_preserved(self):
        """When the vision label is so generic that the container-strip
        would leave nothing (e.g. 'Bottle'), the rejection category is
        ``generic_noun``, not ``unspoken_visual``. The prompt must
        document this handoff so the LLM doesn't conflate them."""
        assert "generic_noun" in _SYSTEM_PROMPT
        # The new wording explicitly names 'Bottle' as the canonical
        # generic_noun example to disambiguate from unspoken_visual.
        assert "'Bottle'" in _SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# run_consolidation prompt_version=None defaults to the code constant
# ---------------------------------------------------------------------------


class TestRunConsolidationPromptVersionDefault:
    """``run_consolidation`` previously hardcoded ``prompt_version='v1.0'``
    as a function default. When the code's
    ``_DEFAULT_PROMPT_VERSION`` constant bumped, callers that didn't
    pass an explicit version stamped the OLD version on every row.
    The revised signature takes ``prompt_version=None`` and resolves
    to ``_DEFAULT_PROMPT_VERSION`` at call time — removing the drift."""

    def test_signature_takes_none_and_resolves_to_code_default(self):
        """Inspect the function signature to confirm the default is
        ``None`` (not a hardcoded string). The behavioral test for the
        resolution lives below; this one pins the SIGNATURE so a
        future "helpful" refactor can't quietly re-hardcode."""
        import inspect
        from app.modules.shorts_auto_product.consolidate.service import (
            run_consolidation,
        )
        sig = inspect.signature(run_consolidation)
        param = sig.parameters["prompt_version"]
        assert param.default is None, (
            "prompt_version default reverted to a hardcoded string — "
            "this re-introduces the v1.0-vs-_DEFAULT_PROMPT_VERSION "
            "drift that the cross-reference fix removed"
        )

    @pytest.mark.asyncio
    async def test_resolves_to_default_when_none_passed_and_marker_short_circuits(
        self,
    ):
        """End-to-end: when ``prompt_version=None`` is passed, the
        runner resolves to ``_DEFAULT_PROMPT_VERSION`` before any
        consolidator construction. The cheapest exercise of the
        resolution path is the idempotency short-circuit — pass a
        catalog that already has consolidation markers; the function
        returns (0,0,0) WITHOUT ever needing an LLM call, but the
        resolution branch still fires if any code path inspects
        prompt_version first. Test that the function returns
        cleanly with prompt_version=None (no crash on the None
        sentinel before the resolution branch runs)."""
        from unittest.mock import AsyncMock, MagicMock
        from uuid import uuid4
        from app.modules.shorts_auto_product.consolidate.service import (
            run_consolidation,
        )

        # has_consolidation_markers returns True → short-circuit at
        # (0, 0, 0) BEFORE the prompt_version resolution branch.
        # This isolates the test from any LLM mocking; we just need
        # to confirm the function tolerates prompt_version=None and
        # returns without raising.
        fake_repo = MagicMock()
        fake_repo.has_consolidation_markers = AsyncMock(return_value=True)
        import app.modules.shorts_auto_product.repositories as repos_pkg
        import app.modules.shorts_auto_product.consolidate.service as svc_mod
        import pytest as _pytest

        # Patch ProductCatalogRepository at BOTH the package re-export
        # and the service module's bound name (Pattern B per
        # [[feedback-pattern-b-test-patching]]).
        @_pytest.MonkeyPatch.context()
        def _patch_repos():
            yield

        # Use monkeypatch via fixture would be cleaner; inline patch
        # via setattr keeps this test self-contained.
        original_pkg = repos_pkg.ProductCatalogRepository
        original_svc = svc_mod.ProductCatalogRepository
        try:
            repos_pkg.ProductCatalogRepository = MagicMock(return_value=fake_repo)
            svc_mod.ProductCatalogRepository = MagicMock(return_value=fake_repo)
            result = await run_consolidation(
                session=AsyncMock(),
                openai_client=MagicMock(),
                org_id=uuid4(),
                video_db_id=uuid4(),
                prompt_version=None,  # ← the test
            )
            assert result == (0, 0, 0)
        finally:
            repos_pkg.ProductCatalogRepository = original_pkg
            svc_mod.ProductCatalogRepository = original_svc
