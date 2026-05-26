"""Tests for ``app.modules.shorts_auto_product.eval.window_score``.

Pure stdlib unit tests — no docker, no DB, no embedder. The scorer
operates on plain ``list[tuple[int, int]]`` so we can pin every
edge case the live picker can produce.
"""

from __future__ import annotations

import pytest

from app.modules.shorts_auto_product.eval.window_score import (
    MEAN_IOU_FAILURE_ACTION,
    MEAN_IOU_FLOOR,
    VideoWindowReport,
    WindowScore,
    aggregate_mean_iou_across_videos,
    evaluate_window_gates,
    score_product,
    score_video,
)


# ---------------------------------------------------------------------------
# score_product — single-product boundary cases
# ---------------------------------------------------------------------------


class TestScoreProduct:
    def test_empty_expected_returns_none(self):
        """No ground truth → cannot grade this product."""
        assert score_product([], [(0, 1000)]) is None

    def test_empty_actual_recall_zero_precision_vacuous(self):
        """Picker emitted nothing → 0 coverage, 1.0 precision (no
        false positives by construction), IoU 0."""
        s = score_product([(0, 1000), (2000, 3000)], [])
        assert s is not None
        assert s.coverage_recall == 0.0
        assert s.selection_precision == 1.0
        assert s.iou == 0.0
        assert s.expected_total_ms == 2000
        assert s.actual_total_ms == 0
        assert s.intersection_ms == 0

    def test_perfect_match(self):
        """Expected and actual identical → 1.0 / 1.0 / 1.0."""
        s = score_product([(1000, 4000)], [(1000, 4000)])
        assert s is not None
        assert s.coverage_recall == 1.0
        assert s.selection_precision == 1.0
        assert s.iou == 1.0
        assert s.intersection_ms == 3000

    def test_disjoint_zero_everywhere(self):
        """Picker chose a totally different range → 0 / 0 / 0."""
        s = score_product([(0, 1000)], [(5000, 6000)])
        assert s is not None
        assert s.coverage_recall == 0.0
        assert s.selection_precision == 0.0
        assert s.iou == 0.0
        assert s.intersection_ms == 0
        assert s.expected_total_ms == 1000
        assert s.actual_total_ms == 1000

    def test_half_overlap_metric_math(self):
        """Expected=[0, 2000), actual=[1000, 3000). Intersection=1000ms.
        Union=3000ms. Recall=1000/2000=0.5; precision=1000/2000=0.5;
        IoU=1000/3000≈0.333."""
        s = score_product([(0, 2000)], [(1000, 3000)])
        assert s is not None
        assert s.intersection_ms == 1000
        assert s.expected_total_ms == 2000
        assert s.actual_total_ms == 2000
        assert s.coverage_recall == 0.5
        assert s.selection_precision == 0.5
        assert s.iou == pytest.approx(1000 / 3000)

    def test_expected_fully_covered_picker_overshoots(self):
        """Picker covered all of expected + more → recall 1.0,
        precision < 1.0, IoU = |E| / |A|."""
        s = score_product([(1000, 2000)], [(0, 5000)])
        assert s is not None
        assert s.coverage_recall == 1.0
        assert s.selection_precision == 1000 / 5000
        assert s.iou == 1000 / 5000

    def test_actual_subset_of_expected(self):
        """Picker covered ONLY part of expected → recall < 1.0,
        precision 1.0, IoU = |A| / |E|."""
        s = score_product([(0, 5000)], [(1000, 2000)])
        assert s is not None
        assert s.coverage_recall == 1000 / 5000
        assert s.selection_precision == 1.0
        assert s.iou == 1000 / 5000

    def test_overlapping_expected_windows_get_merged(self):
        """Two overlapping expected windows merge into one for the
        denominator (otherwise we'd double-count overlapping time)."""
        s = score_product(
            [(0, 3000), (2000, 5000)],  # merges to [(0, 5000)]
            [(0, 5000)],
        )
        assert s is not None
        assert s.expected_total_ms == 5000
        assert s.coverage_recall == 1.0
        assert s.iou == 1.0

    def test_zero_length_windows_dropped(self):
        """``end <= start`` windows carry no time and are dropped."""
        s = score_product(
            [(1000, 2000), (5000, 5000), (3000, 3000)],
            [(1000, 2000)],
        )
        assert s is not None
        assert s.expected_total_ms == 1000

    def test_inverted_windows_dropped(self):
        """``end < start`` is treated as zero-length, NOT flipped."""
        s = score_product(
            [(1000, 2000), (5000, 4000)],  # second window dropped
            [(1000, 2000)],
        )
        assert s is not None
        assert s.expected_total_ms == 1000
        assert s.iou == 1.0

    def test_two_disjoint_windows_partial_match(self):
        """Expected=[(0,1000), (5000,6000)] (2000ms total),
        actual=[(500,5500)] (5000ms). Intersection=500+500=1000ms.
        Recall=1000/2000=0.5; precision=1000/5000=0.2."""
        s = score_product(
            [(0, 1000), (5000, 6000)],
            [(500, 5500)],
        )
        assert s is not None
        assert s.intersection_ms == 1000
        assert s.coverage_recall == 0.5
        assert s.selection_precision == 1000 / 5000

    def test_half_open_no_overlap_at_boundary(self):
        """``[0, 1000)`` and ``[1000, 2000)`` are touching but DO NOT
        overlap under half-open semantics — intersection is 0."""
        s = score_product([(0, 1000)], [(1000, 2000)])
        assert s is not None
        assert s.intersection_ms == 0
        assert s.coverage_recall == 0.0
        assert s.selection_precision == 0.0


# ---------------------------------------------------------------------------
# score_video — multi-product aggregation
# ---------------------------------------------------------------------------


class TestScoreVideo:
    def test_all_products_gradeable_mean_iou_correct(self):
        """Two products, perfect on one, half on the other → mean
        IoU = (1.0 + 0.333) / 2 ≈ 0.667."""
        rep = score_video(
            video_id="gd_test_1",
            expected_per_product={
                "비타민C 세럼": [(0, 1000)],
                "수분 크림": [(0, 2000)],
            },
            actual_per_product={
                "비타민C 세럼": [(0, 1000)],          # perfect
                "수분 크림": [(1000, 3000)],          # half overlap
            },
        )
        assert rep.video_id == "gd_test_1"
        assert rep.products_graded == 2
        assert rep.products_ungradeable == 0
        assert rep.mean_iou == pytest.approx((1.0 + 1000 / 3000) / 2)

    def test_picker_missing_product_scored_as_zero(self):
        """Expected has a product the picker didn't surface at all →
        scored with empty actual → coverage_recall=0, IoU=0. This
        DEFLATES mean_iou, which is the intended signal."""
        rep = score_video(
            video_id="gd_test_2",
            expected_per_product={
                "수분 크림": [(0, 2000)],
                "립밤": [(3000, 5000)],
            },
            actual_per_product={
                "수분 크림": [(0, 2000)],
                # 립밤 absent → treated as actual=[]
            },
        )
        assert rep.products_graded == 2
        lipbalm = rep.per_product["립밤"]
        assert lipbalm is not None
        assert lipbalm.coverage_recall == 0.0
        assert lipbalm.iou == 0.0
        assert rep.mean_iou == pytest.approx(0.5)

    def test_extra_actual_product_ignored(self):
        """Products the picker surfaced but the golden didn't track
        are NOT counted here — that's an enumeration-precision
        question, graded by ``enumeration_score`` instead."""
        rep = score_video(
            video_id="gd_test_3",
            expected_per_product={"립밤": [(0, 1000)]},
            actual_per_product={
                "립밤": [(0, 1000)],
                "정체불명": [(0, 5000)],  # not in expected → ignored
            },
        )
        assert set(rep.per_product.keys()) == {"립밤"}
        assert rep.mean_iou == 1.0

    def test_product_with_no_ground_truth_excluded_from_mean(self):
        """A product whose expected windows merge to zero duration is
        ungradeable (score_product → None). The mean must average
        over gradeable products only — otherwise one bad golden row
        deflates the whole video."""
        rep = score_video(
            video_id="gd_test_4",
            expected_per_product={
                "립밤": [(0, 1000)],
                "노이즈": [],  # ungradeable
            },
            actual_per_product={"립밤": [(0, 1000)]},
        )
        assert rep.products_graded == 1
        assert rep.products_ungradeable == 1
        assert rep.mean_iou == 1.0  # only 립밤 contributes
        assert rep.per_product["노이즈"] is None

    def test_all_products_ungradeable_returns_none_means(self):
        rep = score_video(
            video_id="gd_test_5",
            expected_per_product={"a": [], "b": []},
            actual_per_product={"a": [(0, 100)]},
        )
        assert rep.mean_iou is None
        assert rep.mean_coverage_recall is None
        assert rep.mean_selection_precision is None
        assert rep.products_graded == 0


# ---------------------------------------------------------------------------
# evaluate_window_gates — README floor + failure action
# ---------------------------------------------------------------------------


class TestEvaluateWindowGates:
    def test_pass_at_floor(self):
        gate = evaluate_window_gates(MEAN_IOU_FLOOR)
        assert gate["passed"] is True
        assert gate["failure_action"] is None
        assert gate["floor"] == MEAN_IOU_FLOOR

    def test_pass_above_floor(self):
        gate = evaluate_window_gates(0.75)
        assert gate["passed"] is True
        assert gate["failure_action"] is None

    def test_fail_below_floor_carries_failure_action(self):
        gate = evaluate_window_gates(0.55)
        assert gate["passed"] is False
        assert gate["failure_action"] == MEAN_IOU_FAILURE_ACTION

    def test_none_input_fails_with_descriptive_action(self):
        """``mean_iou=None`` means no products were gradeable — this
        must NOT pass the gate via a default-zero comparison."""
        gate = evaluate_window_gates(None)
        assert gate["passed"] is False
        assert gate["mean_iou"] is None
        assert "no products" in gate["failure_action"]


# ---------------------------------------------------------------------------
# aggregate_mean_iou_across_videos
# ---------------------------------------------------------------------------


class TestAggregateMeanIouAcrossVideos:
    def _video(self, video_id: str, mean_iou: float | None) -> VideoWindowReport:
        return VideoWindowReport(
            video_id=video_id,
            per_product={},
            mean_iou=mean_iou,
            mean_coverage_recall=None,
            mean_selection_precision=None,
            products_graded=0 if mean_iou is None else 1,
            products_ungradeable=0,
        )

    def test_simple_mean(self):
        agg = aggregate_mean_iou_across_videos(
            [self._video("a", 0.4), self._video("b", 0.8)]
        )
        assert agg == pytest.approx(0.6)

    def test_ungradeable_videos_excluded(self):
        agg = aggregate_mean_iou_across_videos(
            [
                self._video("a", 1.0),
                self._video("b", None),  # excluded from denominator
            ]
        )
        assert agg == 1.0

    def test_all_ungradeable_returns_none(self):
        agg = aggregate_mean_iou_across_videos(
            [self._video("a", None), self._video("b", None)]
        )
        assert agg is None

    def test_empty_returns_none(self):
        assert aggregate_mean_iou_across_videos([]) is None
