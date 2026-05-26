"""Pure, importable scorer for product-anchored scene-selection windows.

Grades whether the auto-shorts picker selects scenes that genuinely show
or discuss the operator-selected product. For each ``(video, product)``
pair the golden carries an ``expected_windows_ms`` list (millisecond
[start, end) spans where the annotator marked the product as on-screen
OR being spoken about); the live picker produces an ``actual_windows_ms``
list (the [start, end) spans of the scenes it chose). The three metrics
below answer:

  * Coverage recall   — "did the picker cover the time the product was
    actually featured?"
  * Selection precision — "of the time the picker output, how much was
    actually product-relevant?"
  * Window IoU        — composite (Jaccard on time).

This module is the sibling of :mod:`enumeration_score` — together they
grade the two halves of the product-anchored shorts pipeline:

  * ``enumeration_score`` — did we get the right products in the catalog?
  * ``window_score``      — given a selected product, did we pick the
                            right scene windows?

ZERO IO / DB / network / ``app.*`` imports — stdlib only. The CLI
(``services/api/scripts/eval_shorts_auto_product.py``) feeds plain
``list[tuple[int, int]]`` window lists in here.

Calibration gate (README ``goldens/README.md`` calibration table):

  * Mean window IoU per product ≥ 0.60
    failure action: swap SigLIP2 → DINOv2 before prod
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

# ---------------------------------------------------------------------------
# Gate floors + documented failure actions (mirror goldens/README.md)
# ---------------------------------------------------------------------------

MEAN_IOU_FLOOR = 0.60

MEAN_IOU_FAILURE_ACTION = "Swap SigLIP2 -> DINOv2 before prod"


# ---------------------------------------------------------------------------
# Window primitives — millisecond [start, end) half-open intervals
# ---------------------------------------------------------------------------

Window = tuple[int, int]


def _merge(windows: list[Window]) -> list[Window]:
    """Collapse overlapping half-open intervals into a disjoint cover.

    Half-open semantics: ``[start, end)``. Two adjacent windows
    ``[a, b)`` and ``[b, c)`` are NOT considered overlapping (they
    touch at ``b``) and are kept separate. This matches how the
    picker emits scene boundaries — a scene ending at frame_idx 12000
    and the next starting at frame_idx 12000 share zero ms of overlap.

    Drops zero-length / inverted entries defensively (a window with
    ``end <= start`` carries no time and is never useful to merge).
    """
    cleaned: list[Window] = [(s, e) for s, e in windows if e > s]
    if not cleaned:
        return []
    cleaned.sort()
    out: list[Window] = [cleaned[0]]
    for s, e in cleaned[1:]:
        prev_s, prev_e = out[-1]
        if s < prev_e:  # half-open overlap
            out[-1] = (prev_s, max(prev_e, e))
        else:
            out.append((s, e))
    return out


def _total_duration(merged: list[Window]) -> int:
    """Sum of durations across a disjoint window list. ms."""
    return sum(e - s for s, e in merged)


def _intersection_duration(
    merged_a: list[Window], merged_b: list[Window]
) -> int:
    """Total overlap (ms) between two ALREADY-MERGED window lists.

    Two-pointer sweep over the sorted intervals. Caller MUST pass
    pre-merged lists or the result is wrong — the assertion makes the
    contract auditable in tests.
    """
    i = j = 0
    total = 0
    while i < len(merged_a) and j < len(merged_b):
        s1, e1 = merged_a[i]
        s2, e2 = merged_b[j]
        lo = max(s1, s2)
        hi = min(e1, e2)
        if hi > lo:
            total += hi - lo
        # Advance whichever interval ends first.
        if e1 < e2:
            i += 1
        else:
            j += 1
    return total


# ---------------------------------------------------------------------------
# Per-product score
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowScore:
    """Three metrics for one (video, product) pair.

    All metrics are in ``[0.0, 1.0]``. ``None`` is reserved for the
    "cannot grade" case at the scorer's surface, not here — the
    dataclass always carries concrete numbers.
    """

    coverage_recall: float
    selection_precision: float
    iou: float
    expected_total_ms: int
    actual_total_ms: int
    intersection_ms: int


def score_product(
    expected_windows_ms: list[Window],
    actual_windows_ms: list[Window],
) -> WindowScore | None:
    """Score the picker's output against the annotator's windows.

    Returns ``None`` when the expected set has zero total duration
    after merge — that means there is NO ground-truth time for this
    product and we cannot grade the picker on it (different signal
    from "the picker missed it"; the CLI must distinguish via a
    separate enumeration-recall check).

    Conventions:
      * ``coverage_recall``    — ``|expected ∩ actual| / |expected|``.
      * ``selection_precision`` — ``|expected ∩ actual| / |actual|``.
        Defined as ``1.0`` when ``|actual| == 0`` (the picker didn't
        emit anything, so no false positives by construction —
        vacuously precise).
      * ``iou`` — ``|expected ∩ actual| / |expected ∪ actual|``.
    """
    exp = _merge(expected_windows_ms)
    act = _merge(actual_windows_ms)
    expected_total = _total_duration(exp)
    actual_total = _total_duration(act)
    if expected_total == 0:
        return None
    intersection = _intersection_duration(exp, act)
    union = expected_total + actual_total - intersection
    return WindowScore(
        coverage_recall=intersection / expected_total,
        selection_precision=(
            intersection / actual_total if actual_total > 0 else 1.0
        ),
        iou=intersection / union if union > 0 else 1.0,
        expected_total_ms=expected_total,
        actual_total_ms=actual_total,
        intersection_ms=intersection,
    )


# ---------------------------------------------------------------------------
# Per-video aggregate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VideoWindowReport:
    """Per-video aggregate.

    ``per_product`` maps product label → score (or ``None`` for products
    that had no ground-truth windows). ``mean_iou`` averages IoU over
    products WITH ground-truth (None entries are excluded from the
    denominator so a video with one ungradeable product doesn't
    artificially deflate the mean).
    """

    video_id: str
    per_product: dict[str, WindowScore | None]
    mean_iou: float | None
    mean_coverage_recall: float | None
    mean_selection_precision: float | None
    products_graded: int
    products_ungradeable: int


def score_video(
    *,
    video_id: str,
    expected_per_product: dict[str, list[Window]],
    actual_per_product: dict[str, list[Window]],
) -> VideoWindowReport:
    """Score every product in a video, then take per-metric means.

    The keys are the canonical product label (``label_kr`` from the
    golden — the same string the enumeration matcher uses). Products
    in ``expected_per_product`` that are absent from
    ``actual_per_product`` are scored as if the picker emitted an
    empty window list (coverage_recall=0, selection_precision=1.0 by
    the vacuous-precision rule, iou=0).

    Products in ``actual_per_product`` that are NOT in
    ``expected_per_product`` are ignored at this layer — they're
    enumeration-precision questions (catalog pollution), graded by
    :mod:`enumeration_score`.
    """
    per_product: dict[str, WindowScore | None] = {}
    for label, expected in expected_per_product.items():
        actual = actual_per_product.get(label, [])
        per_product[label] = score_product(expected, actual)

    graded = [s for s in per_product.values() if s is not None]
    products_graded = len(graded)
    products_ungradeable = len(per_product) - products_graded

    if products_graded == 0:
        return VideoWindowReport(
            video_id=video_id,
            per_product=per_product,
            mean_iou=None,
            mean_coverage_recall=None,
            mean_selection_precision=None,
            products_graded=0,
            products_ungradeable=products_ungradeable,
        )
    return VideoWindowReport(
        video_id=video_id,
        per_product=per_product,
        mean_iou=fmean(s.iou for s in graded),
        mean_coverage_recall=fmean(s.coverage_recall for s in graded),
        mean_selection_precision=fmean(s.selection_precision for s in graded),
        products_graded=products_graded,
        products_ungradeable=products_ungradeable,
    )


# ---------------------------------------------------------------------------
# Cross-video aggregate + gate
# ---------------------------------------------------------------------------


def evaluate_window_gates(mean_iou: float | None) -> dict:
    """Apply the README mean-window-IoU floor.

    ``mean_iou=None`` (no products gradeable) maps to ``passed=False``
    so a video with zero ground truth doesn't accidentally pass the
    gate. The CLI should also surface the ungradeable count separately
    so the operator can tell "every product was ungradeable" from
    "every gradeable product flunked the floor".
    """
    if mean_iou is None:
        return {
            "passed": False,
            "mean_iou": None,
            "floor": MEAN_IOU_FLOOR,
            "failure_action": (
                "no products had ground-truth windows — cannot grade"
            ),
        }
    passed = mean_iou >= MEAN_IOU_FLOOR
    return {
        "passed": passed,
        "mean_iou": mean_iou,
        "floor": MEAN_IOU_FLOOR,
        "failure_action": None if passed else MEAN_IOU_FAILURE_ACTION,
    }


def aggregate_mean_iou_across_videos(
    reports: list[VideoWindowReport],
) -> float | None:
    """Cross-video mean of per-video ``mean_iou`` values.

    Videos with ``mean_iou is None`` (no gradeable products) are
    excluded from the denominator. Returns ``None`` if every video is
    ungradeable.
    """
    gradeable = [r.mean_iou for r in reports if r.mean_iou is not None]
    if not gradeable:
        return None
    return fmean(gradeable)
