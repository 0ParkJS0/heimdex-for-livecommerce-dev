"""Unit tests for the PURE enumeration-eval scorer.

NO DB / IO / network — exercises ``app.modules.shorts_auto_product.eval.
enumeration_score`` on synthetic data only. The eval CLI itself
(``scripts/eval_shorts_auto_product.py``) stays out of CI because it
spends real OpenAI + Aircloud GPU budget; this module is the part that
belongs in the allowlist.
"""

from __future__ import annotations

import math

import pytest

from app.modules.shorts_auto_product.eval.enumeration_score import (
    DEFAULT_COSINE_THRESHOLD,
    PRECISION_FAILURE_ACTION,
    PRECISION_FLOOR,
    RECALL_FAILURE_ACTION,
    RECALL_FLOOR,
    CosineLabelMatcher,
    Embedder,
    ExpectedProduct,
    GoldenSet,
    JaccardLabelMatcher,
    _cosine_sim,
    enumeration_precision,
    enumeration_recall,
    evaluate_gates,
)

MATCHER = JaccardLabelMatcher()


# ---------------------------------------------------------------------------
# Deterministic stub embedder for CosineLabelMatcher tests
# ---------------------------------------------------------------------------


class _StubEmbedder:
    """Maps a closed vocabulary of labels to hand-tuned 4-d vectors.

    Lets the test pin exact cosine outcomes ("포기김치 봉지" ↔ "종가
    일상행복 포기김치 10kg" should match at the README's 0.65 floor) WITHOUT
    a live OpenAI call. The class doubles as a Protocol-conformance test:
    it has no inheritance, only the ``embed`` method — if it satisfies
    ``isinstance(stub, Embedder)`` the matcher will accept it.
    """

    def __init__(self, table: dict[str, list[float]]) -> None:
        self._table = {k: list(v) for k, v in table.items()}
        self.call_count = 0
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Record + count so we can assert prime() batches into 1 call.
        self.call_count += 1
        self.calls.append(list(texts))
        out: list[list[float]] = []
        for t in texts:
            if t not in self._table:
                raise KeyError(
                    f"stub embedder has no entry for {t!r} — extend the "
                    f"test's _StubEmbedder table"
                )
            out.append(list(self._table[t]))
        return out


def _expected(*labels: str) -> list[ExpectedProduct]:
    return [ExpectedProduct(label_kr=label) for label in labels]


# ---------------------------------------------------------------------------
# Label matcher behavior
# ---------------------------------------------------------------------------


def test_matcher_variant_of_same_name_matches():
    # Extra modifier word + different spacing — shares enough tokens.
    assert MATCHER.matches("핑크 세럼 병", "핑크 세럼")
    # Width/compat + casing drift collapses under NFKC + casefold.
    assert MATCHER.matches("Serum Bottle", "serum bottle")
    assert MATCHER.matches("ＡＢＣ 토너", "ABC 토너")


def test_matcher_different_product_does_not_match():
    assert not MATCHER.matches("핑크 세럼 병", "검정 클렌징 폼")
    assert not MATCHER.matches("serum bottle", "studio ring light")


def test_matcher_empty_label_never_matches():
    assert not MATCHER.matches("", "핑크 세럼")
    assert not MATCHER.matches("핑크 세럼", "")


def test_matcher_threshold_is_tunable():
    strict = JaccardLabelMatcher(threshold=0.99)
    # One shared token of three total → Jaccard 1/3 < 0.99.
    assert not strict.matches("핑크 세럼 병", "핑크 토너 통")
    loose = JaccardLabelMatcher(threshold=0.2)
    assert loose.matches("핑크 세럼 병", "핑크 토너 통")


# ---------------------------------------------------------------------------
# Recall
# ---------------------------------------------------------------------------


def test_full_recall():
    expected = _expected("핑크 세럼 병", "검정 클렌징 폼", "ABC 토너")
    actual = ["핑크 세럼", "검정 클렌징 폼", "ABC 토너 200ml"]
    assert enumeration_recall(expected, actual, MATCHER) == 1.0


def test_partial_recall_some_expected_missed():
    expected = _expected("핑크 세럼 병", "검정 클렌징 폼", "노란 선크림")
    # Only the first two are surfaced; 선크림 is missing.
    actual = ["핑크 세럼 병", "검정 클렌징 폼"]
    assert enumeration_recall(expected, actual, MATCHER) == pytest.approx(2 / 3)


def test_recall_zero_when_nothing_matches():
    expected = _expected("핑크 세럼 병", "검정 클렌징 폼")
    actual = ["스튜디오 조명", "호스트 시계"]
    assert enumeration_recall(expected, actual, MATCHER) == 0.0


def test_recall_empty_expected_is_one():
    assert enumeration_recall([], ["아무거나"], MATCHER) == 1.0


def test_recall_matches_via_en_hint():
    expected = [
        ExpectedProduct(label_kr="핑크 세럼 병", label_en_hint="pink serum bottle")
    ]
    # Catalog label is English-ish; KR fails but EN hint matches.
    actual = ["pink serum bottle"]
    assert enumeration_recall(expected, actual, MATCHER) == 1.0


# ---------------------------------------------------------------------------
# Precision
# ---------------------------------------------------------------------------


def test_precision_with_negatives_present():
    # 1 of 3 actual labels matches a curated negative → precision 2/3.
    actual = ["핑크 세럼 병", "검정 클렌징 폼", "스튜디오 조명"]
    negatives = ["스튜디오 조명", "호스트 시계"]
    assert enumeration_precision(actual, negatives, MATCHER) == pytest.approx(2 / 3)


def test_precision_clean_catalog_is_one():
    actual = ["핑크 세럼 병", "검정 클렌징 폼"]
    negatives = ["스튜디오 조명"]
    assert enumeration_precision(actual, negatives, MATCHER) == 1.0


def test_precision_no_negatives_is_one():
    actual = ["핑크 세럼 병", "스튜디오 조명"]
    assert enumeration_precision(actual, [], MATCHER) == 1.0


def test_precision_no_actual_labels_is_one():
    assert enumeration_precision([], ["스튜디오 조명"], MATCHER) == 1.0


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def test_gate_pass():
    report = evaluate_gates(recall=0.90, precision=0.85)
    assert report["passed"] is True
    assert report["recall"]["passed"] is True
    assert report["precision"]["passed"] is True
    assert report["recall"]["failure_action"] is None
    assert report["precision"]["failure_action"] is None
    assert report["recall"]["floor"] == RECALL_FLOOR
    assert report["precision"]["floor"] == PRECISION_FLOOR


def test_gate_fail_recall_only():
    report = evaluate_gates(recall=0.50, precision=0.95)
    assert report["passed"] is False
    assert report["recall"]["passed"] is False
    assert report["recall"]["failure_action"] == RECALL_FAILURE_ACTION
    assert report["precision"]["passed"] is True
    assert report["precision"]["failure_action"] is None


def test_gate_fail_precision_only():
    report = evaluate_gates(recall=0.95, precision=0.50)
    assert report["passed"] is False
    assert report["precision"]["passed"] is False
    assert report["precision"]["failure_action"] == PRECISION_FAILURE_ACTION
    assert report["recall"]["passed"] is True
    assert report["recall"]["failure_action"] is None


def test_gate_fail_both():
    report = evaluate_gates(recall=0.10, precision=0.10)
    assert report["passed"] is False
    assert report["recall"]["failure_action"] == RECALL_FAILURE_ACTION
    assert report["precision"]["failure_action"] == PRECISION_FAILURE_ACTION


def test_gate_exactly_at_floor_passes():
    # Floors are inclusive (≥), so exactly-on-floor is a pass.
    report = evaluate_gates(recall=RECALL_FLOOR, precision=PRECISION_FLOOR)
    assert report["passed"] is True


# ---------------------------------------------------------------------------
# Golden parsing (from-dict round-trip of the README schema)
# ---------------------------------------------------------------------------


def test_expected_product_from_dict():
    raw = {
        "label_kr": "핑크 세럼 병",
        "label_en_hint": "pink serum bottle",
        "first_appearance_ms": 14200,
        "expected_appearance_count_min": 4,
        "expected_total_seconds_min": 28,
        "category_hint": "skincare",
    }
    exp = ExpectedProduct.from_dict(raw)
    assert exp.label_kr == "핑크 세럼 병"
    assert exp.label_en_hint == "pink serum bottle"
    assert exp.first_appearance_ms == 14200
    assert exp.match_texts() == ["핑크 세럼 병", "pink serum bottle"]


def test_golden_set_from_dict():
    raw = {
        "$schema_version": "1",
        "video_id": "gd_overlay_001",
        "org_slug": "devorg",
        "category": "overlay",
        "enumeration_prompt_version": "v1.0",
        "enumeration_version": "v1.0",
        "tracker_version": "v1.0",
        "expected_products": [{"label_kr": "핑크 세럼 병"}],
        "expected_negatives": ["스튜디오 조명"],
    }
    golden = GoldenSet.from_dict(raw)
    assert golden.video_id == "gd_overlay_001"
    assert golden.org_slug == "devorg"
    assert golden.category == "overlay"
    assert golden.enumeration_prompt_version == "v1.0"
    assert len(golden.expected_products) == 1
    assert golden.expected_products[0].label_kr == "핑크 세럼 병"
    assert golden.expected_negatives == ["스튜디오 조명"]
    assert golden.schema_version == "1"


# ---------------------------------------------------------------------------
# Unified vision + overlay: scorer is source-agnostic
# ---------------------------------------------------------------------------


def test_scorer_is_enumeration_source_agnostic():
    # The catalog labels could come from vision OR overlay rows — the
    # scorer only sees label strings, so the same golden grades both.
    expected = _expected("핑크 세럼 병", "검정 클렌징 폼")
    vision_and_overlay_labels = ["핑크 세럼 병", "검정 클렌징 폼"]
    assert enumeration_recall(expected, vision_and_overlay_labels, MATCHER) == 1.0
    assert enumeration_precision(vision_and_overlay_labels, [], MATCHER) == 1.0


# ---------------------------------------------------------------------------
# _extract_picker_windows_from_spec — CLI helper that turns a historical
# composition spec dict into the (start_ms, end_ms) windows the scene-
# selection scorer consumes. The DB query itself is integration-tested
# implicitly when the CLI runs against staging; this layer pins the
# JSON-parsing rules so they don't drift.
# ---------------------------------------------------------------------------


def _spec(*clips: dict) -> dict:
    return {"scene_clips": list(clips)}


def _clip(
    *,
    video_id: str,
    start_ms: int,
    end_ms: int,
    scene_id: str = "scene_001",
) -> dict:
    return {
        "scene_id": scene_id,
        "video_id": video_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
    }


def test_extract_picker_windows_happy_path():
    from scripts.eval_shorts_auto_product import _extract_picker_windows_from_spec
    spec = _spec(
        _clip(video_id="gd_target", start_ms=10000, end_ms=20000),
        _clip(video_id="gd_target", start_ms=30000, end_ms=45000),
    )
    assert _extract_picker_windows_from_spec(spec, "gd_target") == [
        (10000, 20000), (30000, 45000),
    ]


def test_extract_picker_windows_filters_cross_source_clips():
    """Composition can mix multiple source videos. Only clips drawn
    from the target source count — anything else is the picker drawing
    from a different reel and must not credit the target's IoU."""
    from scripts.eval_shorts_auto_product import _extract_picker_windows_from_spec
    spec = _spec(
        _clip(video_id="gd_target", start_ms=10000, end_ms=20000),
        _clip(video_id="gd_OTHER", start_ms=0, end_ms=99999),
        _clip(video_id="gd_target", start_ms=30000, end_ms=45000),
    )
    assert _extract_picker_windows_from_spec(spec, "gd_target") == [
        (10000, 20000), (30000, 45000),
    ]


def test_extract_picker_windows_handles_empty_or_malformed():
    from scripts.eval_shorts_auto_product import _extract_picker_windows_from_spec
    # None / non-dict spec
    assert _extract_picker_windows_from_spec(None, "gd_target") == []
    assert _extract_picker_windows_from_spec("not a dict", "gd_target") == []  # type: ignore[arg-type]
    # Missing scene_clips
    assert _extract_picker_windows_from_spec({}, "gd_target") == []
    # Non-dict clip entry
    assert _extract_picker_windows_from_spec(
        {"scene_clips": ["not a dict", {"video_id": "gd_target", "start_ms": 0, "end_ms": 5000}]},
        "gd_target",
    ) == [(0, 5000)]


def test_extract_picker_windows_drops_invalid_times():
    """Inverted / zero-length / non-int ms values are dropped — the
    window scorer would drop them too, but doing it here keeps the
    report counts honest (clips that contributed nothing don't inflate
    the per-product picker-windows count)."""
    from scripts.eval_shorts_auto_product import _extract_picker_windows_from_spec
    spec = _spec(
        _clip(video_id="gd_target", start_ms=10000, end_ms=10000),  # zero
        _clip(video_id="gd_target", start_ms=20000, end_ms=15000),  # inverted
        {"video_id": "gd_target", "start_ms": "bad", "end_ms": 5000},  # type
        {"video_id": "gd_target", "start_ms": 1000},  # missing end_ms
        _clip(video_id="gd_target", start_ms=30000, end_ms=45000),  # ok
    )
    assert _extract_picker_windows_from_spec(spec, "gd_target") == [(30000, 45000)]


# ---------------------------------------------------------------------------
# _cosine_sim — pure math sanity (so a wrong-sign / wrong-norm bug is
# caught at the unit-test layer, not via a degraded staging baseline).
# ---------------------------------------------------------------------------


class TestCosineSim:
    def test_identical_vectors_score_one(self):
        assert _cosine_sim([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        assert _cosine_sim([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors_score_negative_one(self):
        assert _cosine_sim([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero_not_nan(self):
        """A zero-norm vector would divide-by-zero — must short-circuit
        to 0.0 so a degenerate cache entry can never poison ``matches``."""
        assert _cosine_sim([0.0, 0.0], [1.0, 1.0]) == 0.0
        assert _cosine_sim([1.0, 1.0], [0.0, 0.0]) == 0.0

    def test_dim_mismatch_raises(self):
        """Surfaces a model-swap mid-cache loudly rather than returning
        a silently-wrong scalar (matches the docstring contract)."""
        with pytest.raises(ValueError, match="dim mismatch"):
            _cosine_sim([1.0, 0.0], [1.0, 0.0, 0.0])

    def test_known_value_half(self):
        """45° angle ≈ cos(π/4) ≈ 0.7071. Pins the math, not just the
        edge cases — catches sign flips and norm-vs-not-norm swaps."""
        sim = _cosine_sim([1.0, 0.0], [1.0, 1.0])
        assert sim == pytest.approx(1 / math.sqrt(2))


# ---------------------------------------------------------------------------
# CosineLabelMatcher — behaviour against a deterministic stub embedder
# ---------------------------------------------------------------------------


class TestCosineLabelMatcher:
    def _table(self) -> dict[str, list[float]]:
        """Stable 4-d label space mocking the on-staging label drift case.

        Coords are hand-picked so cosine sims line up like the real
        text-embedding-3-small clusters we observed in the 2026-05-26
        baseline: the two kimchi labels live very near each other; the
        Osulloc and host-watch labels are orthogonal.

        We embed the NORMALIZED form (post `_normalize`) because the
        matcher caches/queries by that key.
        """
        return {
            # kimchi cluster (cos ≈ 0.98 — should clear 0.65)
            "포기김치 봉지": [0.99, 0.10, 0.0, 0.0],
            "종가 일상행복 포기김치 10kg": [0.95, 0.30, 0.0, 0.0],
            # osulloc cluster (cos ≈ 0.99 — should clear 0.65)
            "osulloc 티": [0.0, 0.0, 0.99, 0.10],
            "프리미엄 티 컬렉션 90입": [0.0, 0.0, 0.95, 0.30],
            # negatives
            "호스트 시계": [0.0, 1.0, 0.0, 0.0],
            "스튜디오 조명": [0.20, 0.97, 0.0, 0.0],
        }

    def test_matches_brand_stripped_to_full_sku(self):
        """The killer case: vision-pass label vs. golden SKU. Token-
        Jaccard scores 0.20 (no match at floor 0.5); cosine should
        bridge them at the README's 0.65 floor."""
        stub = _StubEmbedder(self._table())
        matcher = CosineLabelMatcher(stub)
        assert matcher.matches("포기김치 봉지", "종가 일상행복 포기김치 10kg")
        assert matcher.matches("OSULLOC 티", "프리미엄 티 컬렉션 90입")

    def test_rejects_clearly_different_products(self):
        stub = _StubEmbedder(self._table())
        matcher = CosineLabelMatcher(stub)
        assert not matcher.matches("포기김치 봉지", "호스트 시계")
        assert not matcher.matches("OSULLOC 티", "스튜디오 조명")

    def test_threshold_is_tunable(self):
        """Above-threshold pair stays matched at 0.65; raising the floor
        past the pair's cosine flips the verdict."""
        stub = _StubEmbedder(self._table())
        # Pair has cos ≈ 0.98 → matches at 0.65 + 0.95, fails at 0.999.
        loose = CosineLabelMatcher(stub, threshold=0.65)
        strict = CosineLabelMatcher(_StubEmbedder(self._table()), threshold=0.999)
        assert loose.matches("포기김치 봉지", "종가 일상행복 포기김치 10kg")
        assert not strict.matches("포기김치 봉지", "종가 일상행복 포기김치 10kg")

    def test_default_threshold_matches_readme(self):
        assert DEFAULT_COSINE_THRESHOLD == 0.65
        stub = _StubEmbedder(self._table())
        matcher = CosineLabelMatcher(stub)
        assert matcher.threshold == 0.65

    def test_empty_label_never_matches(self):
        stub = _StubEmbedder(self._table())
        matcher = CosineLabelMatcher(stub)
        assert not matcher.matches("", "포기김치 봉지")
        assert not matcher.matches("포기김치 봉지", "")
        assert not matcher.matches("   ", "포기김치 봉지")
        # Empty inputs must NOT trigger an embed() call — the stub
        # raises on KeyError, so a regression would surface as a test
        # failure here, not as silent zero-vector matches.
        assert stub.call_count == 0

    def test_normalized_equality_short_circuits_without_embed(self):
        """Self-similarity dodges the embed() round-trip; the stub
        would still answer "match" because cos(v, v) = 1.0, but we
        explicitly want zero API spend on the easy case."""
        stub = _StubEmbedder(self._table())
        matcher = CosineLabelMatcher(stub)
        assert matcher.matches("포기김치 봉지", "포기김치 봉지")
        assert matcher.matches("포기김치 봉지", "ＡＢＣ 포기김치 봉지".replace("ＡＢＣ ", ""))
        assert stub.call_count == 0

    def test_normalized_equality_with_width_and_case_variants(self):
        """``_normalize`` is NFKC + casefold, so fullwidth + uppercase
        variants must collapse to a cache hit / short-circuit."""
        stub = _StubEmbedder(self._table())
        matcher = CosineLabelMatcher(stub)
        # "OSULLOC 티" → "osulloc 티" via casefold; matches itself.
        assert matcher.matches("OSULLOC 티", "OSULLOC 티")
        # ASCII vs fullwidth ABCs normalise to the same key.
        # Use a label NOT in the stub table to prove normalisation +
        # short-circuit kick in before any embed() lookup.
        assert matcher.matches("ＡＢＣ", "ABC")
        assert stub.call_count == 0

    def test_prime_batches_into_one_embed_call(self):
        """Performance contract: prime() makes ONE batched call no
        matter how many labels are seeded. A regression to 1-call-per-
        label would 10x the cost without changing the JSON output."""
        stub = _StubEmbedder(self._table())
        matcher = CosineLabelMatcher(stub)
        matcher.prime(
            [
                "포기김치 봉지",
                "종가 일상행복 포기김치 10kg",
                "호스트 시계",
                "스튜디오 조명",
            ]
        )
        assert stub.call_count == 1
        assert matcher.cache_size == 4

    def test_prime_is_idempotent(self):
        """Calling prime twice with the same labels MUST NOT re-embed."""
        stub = _StubEmbedder(self._table())
        matcher = CosineLabelMatcher(stub)
        matcher.prime(["포기김치 봉지", "종가 일상행복 포기김치 10kg"])
        assert stub.call_count == 1
        matcher.prime(["포기김치 봉지", "종가 일상행복 포기김치 10kg"])
        assert stub.call_count == 1  # no new call
        matcher.prime(["호스트 시계"])  # new label
        assert stub.call_count == 2

    def test_prime_skips_empty_and_whitespace(self):
        stub = _StubEmbedder(self._table())
        matcher = CosineLabelMatcher(stub)
        matcher.prime(["포기김치 봉지", "", "   ", None])  # type: ignore[list-item]
        # Only the real label embedded; cache_size proves whitespace
        # didn't insert a poison entry.
        assert matcher.cache_size == 1

    def test_matches_lazy_fills_missing_pair(self):
        """The CLI primes per-video, but the matcher must still answer
        correctly when called on an unprimed pair (defensive contract)."""
        stub = _StubEmbedder(self._table())
        matcher = CosineLabelMatcher(stub)
        # No prime() call — matches must trigger embed().
        assert matcher.matches("포기김치 봉지", "종가 일상행복 포기김치 10kg")
        assert stub.call_count == 1  # batched the missing pair
        assert matcher.cache_size == 2

    def test_protocol_conformance(self):
        """Stub satisfies the Embedder Protocol — no inheritance needed."""
        stub = _StubEmbedder(self._table())
        assert isinstance(stub, Embedder)

    def test_used_as_jaccard_drop_in_for_enumeration_recall(self):
        """End-to-end: swap the matcher into ``enumeration_recall`` and
        verify the brand-stripped vs SKU pair now contributes to recall.
        This is the exact gap the 2026-05-26 baseline (0.107 recall)
        was hitting; under the cosine matcher both expected products
        get matched and recall = 1.0."""
        stub = _StubEmbedder(self._table())
        matcher = CosineLabelMatcher(stub)
        expected = [
            ExpectedProduct(label_kr="종가 일상행복 포기김치 10kg"),
            ExpectedProduct(label_kr="프리미엄 티 컬렉션 90입"),
        ]
        actual = ["포기김치 봉지", "OSULLOC 티"]
        # Jaccard floor (0.5) would yield recall 0.0 here; cosine 0.65
        # lifts it to 1.0 — the whole point of this PR.
        assert enumeration_recall(expected, actual, MATCHER) == 0.0
        assert enumeration_recall(expected, actual, matcher) == 1.0

    def test_used_as_jaccard_drop_in_for_enumeration_precision(self):
        """Negative pollution detection also benefits from cosine. A
        catalog label that's near-cosine to an ``expected_negative``
        (e.g. "스튜디오 조명" close to "호스트 시계" in the stub) gets
        counted as polluted."""
        stub = _StubEmbedder(self._table())
        matcher = CosineLabelMatcher(stub)
        # Exact-match negative — both matchers catch this.
        actual = ["포기김치 봉지", "호스트 시계"]
        negatives = ["호스트 시계"]
        assert enumeration_precision(actual, negatives, MATCHER) == pytest.approx(0.5)
        assert enumeration_precision(actual, negatives, matcher) == pytest.approx(0.5)
