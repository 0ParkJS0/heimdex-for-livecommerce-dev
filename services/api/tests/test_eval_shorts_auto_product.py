"""Unit tests for the PURE enumeration-eval scorer.

NO DB / IO / network — exercises ``app.modules.shorts_auto_product.eval.
enumeration_score`` on synthetic data only. The eval CLI itself
(``scripts/eval_shorts_auto_product.py``) stays out of CI because it
spends real OpenAI + Aircloud GPU budget; this module is the part that
belongs in the allowlist.
"""

from __future__ import annotations

import pytest

from app.modules.shorts_auto_product.eval.enumeration_score import (
    PRECISION_FAILURE_ACTION,
    PRECISION_FLOOR,
    RECALL_FAILURE_ACTION,
    RECALL_FLOOR,
    ExpectedProduct,
    GoldenSet,
    JaccardLabelMatcher,
    enumeration_precision,
    enumeration_recall,
    evaluate_gates,
)

MATCHER = JaccardLabelMatcher()


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
