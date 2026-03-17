# pyright: reportUnknownMemberType=false, reportUnusedFunction=false, reportExplicitAny=false, reportAny=false
"""
Unit tests for the scene grouping algorithm (pure functions).

Tests cover:
1. _dot_product — basic math, edge cases (empty, mismatched)
2. compute_pairwise_similarity — adaptive signal fusion, all 4 branches
3. find_group_boundaries — threshold detection, edge cases
4. _merge_small_groups — undersized group merging

Run with: pytest tests/test_grouping_algorithm.py -v
"""

import math

import pytest

from app.modules.grouping.algorithm import (
    _dot_product,
    _merge_small_groups,
    compute_pairwise_similarity,
    find_group_boundaries,
)


# ======================================================================
# Helpers
# ======================================================================


def _make_scene(
    start_ms: int = 0,
    *,
    text_emb: list[float] | None = None,
    vis_emb: list[float] | None = None,
) -> dict[str, object]:
    """Build a minimal scene dict for algorithm tests."""
    scene: dict[str, object] = {
        "scene_id": f"scene_{start_ms}",
        "start_ms": start_ms,
        "end_ms": start_ms + 10_000,
    }
    if text_emb is not None:
        scene["embedding_vector"] = text_emb
    if vis_emb is not None:
        scene["visual_embedding"] = vis_emb
    return scene


def _unit_vec(dim: int, idx: int = 0) -> list[float]:
    """Unit vector in the given dimension. All zeros except index `idx` = 1.0."""
    v = [0.0] * dim
    v[idx % dim] = 1.0
    return v


def _uniform_vec(dim: int, value: float = 1.0) -> list[float]:
    """Uniform vector (all elements = value / sqrt(dim)), L2-normalized."""
    norm = math.sqrt(dim) * abs(value)
    if norm == 0:
        return [0.0] * dim
    return [value / norm] * dim


# ======================================================================
# _dot_product
# ======================================================================


class TestDotProduct:
    def test_identical_unit_vectors(self) -> None:
        v = _unit_vec(3, 0)
        assert _dot_product(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        a = _unit_vec(3, 0)
        b = _unit_vec(3, 1)
        assert _dot_product(a, b) == pytest.approx(0.0)

    def test_simple_dot(self) -> None:
        assert _dot_product([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]) == pytest.approx(32.0)

    def test_empty_vectors(self) -> None:
        assert _dot_product([], []) == 0.0

    def test_mismatched_lengths(self) -> None:
        assert _dot_product([1.0, 2.0], [1.0]) == 0.0

    def test_one_empty(self) -> None:
        assert _dot_product([1.0], []) == 0.0
        assert _dot_product([], [1.0]) == 0.0

    def test_single_element(self) -> None:
        assert _dot_product([0.5], [0.5]) == pytest.approx(0.25)


# ======================================================================
# compute_pairwise_similarity
# ======================================================================


class TestComputePairwiseSimilarity:
    def test_empty_scenes(self) -> None:
        assert compute_pairwise_similarity([]) == []

    def test_single_scene(self) -> None:
        assert compute_pairwise_similarity([_make_scene(0)]) == []

    def test_two_identical_scenes_text_only(self) -> None:
        """Two scenes with identical text embeddings → similarity 1.0."""
        v = _uniform_vec(4)
        scenes = [
            _make_scene(0, text_emb=v),
            _make_scene(10000, text_emb=v),
        ]
        sims = compute_pairwise_similarity(scenes)
        assert len(sims) == 1
        assert sims[0] == pytest.approx(1.0, abs=1e-6)

    def test_two_orthogonal_scenes_text_only(self) -> None:
        """Two scenes with orthogonal text embeddings → similarity 0.0."""
        scenes = [
            _make_scene(0, text_emb=_unit_vec(4, 0)),
            _make_scene(10000, text_emb=_unit_vec(4, 1)),
        ]
        sims = compute_pairwise_similarity(scenes)
        assert len(sims) == 1
        assert sims[0] == pytest.approx(0.0)

    def test_visual_only(self) -> None:
        """When only visual embeddings present, uses visual alone."""
        v = _uniform_vec(3)
        scenes = [
            _make_scene(0, vis_emb=v),
            _make_scene(10000, vis_emb=v),
        ]
        sims = compute_pairwise_similarity(scenes)
        assert sims[0] == pytest.approx(1.0, abs=1e-6)

    def test_both_signals_weighted(self) -> None:
        """Both text + visual → weighted average with default 0.6/0.4 weights."""
        # text: identical → 1.0, visual: orthogonal → 0.0
        text_v = _uniform_vec(4)
        scenes = [
            _make_scene(0, text_emb=text_v, vis_emb=_unit_vec(3, 0)),
            _make_scene(10000, text_emb=text_v, vis_emb=_unit_vec(3, 1)),
        ]
        sims = compute_pairwise_similarity(scenes)
        # expected: (0.6 * 1.0 + 0.4 * 0.0) / (0.6 + 0.4) = 0.6
        assert sims[0] == pytest.approx(0.6, abs=1e-6)

    def test_no_embeddings_returns_neutral(self) -> None:
        """Scenes without any embeddings → 0.5 neutral score."""
        scenes = [_make_scene(0), _make_scene(10000)]
        sims = compute_pairwise_similarity(scenes)
        assert sims[0] == pytest.approx(0.5)

    def test_partial_embeddings_mixed(self) -> None:
        """First pair has text, second pair has neither."""
        v = _uniform_vec(4)
        scenes = [
            _make_scene(0, text_emb=v),
            _make_scene(10000, text_emb=v),
            _make_scene(20000),  # no embeddings
        ]
        sims = compute_pairwise_similarity(scenes)
        assert len(sims) == 2
        assert sims[0] == pytest.approx(1.0, abs=1e-6)  # both have text
        assert sims[1] == pytest.approx(0.5)  # second has no embedding

    def test_one_side_missing_text(self) -> None:
        """One scene has text embedding, the other doesn't → has_text is False."""
        v = _uniform_vec(4)
        scenes = [
            _make_scene(0, text_emb=v),
            _make_scene(10000),  # no embedding
        ]
        sims = compute_pairwise_similarity(scenes)
        assert sims[0] == pytest.approx(0.5)  # neither has_text nor has_visual

    def test_custom_weights(self) -> None:
        """Custom text_weight=0.3, visual_weight=0.7."""
        text_v = _uniform_vec(4)
        vis_v = _uniform_vec(3)
        scenes = [
            _make_scene(0, text_emb=text_v, vis_emb=vis_v),
            _make_scene(10000, text_emb=text_v, vis_emb=_unit_vec(3, 1)),
        ]
        sims = compute_pairwise_similarity(
            scenes, text_weight=0.3, visual_weight=0.7,
        )
        # text sim = 1.0, visual sim = dot(uniform, unit_1)
        vis_sim = _dot_product(vis_v, _unit_vec(3, 1))
        expected = (0.3 * 1.0 + 0.7 * vis_sim) / (0.3 + 0.7)
        assert sims[0] == pytest.approx(expected, abs=1e-6)

    def test_clamping(self) -> None:
        """Result is clamped to [0, 1] even with extreme values."""
        # Use large non-normalized vectors that would produce dot > 1.0
        big = [10.0, 10.0]
        scenes = [
            _make_scene(0, text_emb=big),
            _make_scene(10000, text_emb=big),
        ]
        sims = compute_pairwise_similarity(scenes)
        assert sims[0] == 1.0  # clamped

    def test_three_scenes_returns_two_scores(self) -> None:
        v = _uniform_vec(4)
        scenes = [
            _make_scene(0, text_emb=v),
            _make_scene(10000, text_emb=v),
            _make_scene(20000, text_emb=v),
        ]
        sims = compute_pairwise_similarity(scenes)
        assert len(sims) == 2

    def test_n_scenes_returns_n_minus_1_scores(self) -> None:
        """Verify count invariant for N scenes."""
        v = _uniform_vec(4)
        n = 10
        scenes = [_make_scene(i * 10000, text_emb=v) for i in range(n)]
        sims = compute_pairwise_similarity(scenes)
        assert len(sims) == n - 1


# ======================================================================
# find_group_boundaries
# ======================================================================


class TestFindGroupBoundaries:
    def test_empty(self) -> None:
        assert find_group_boundaries([], 0) == []

    def test_single_scene(self) -> None:
        assert find_group_boundaries([], 1) == [(0, 0)]

    def test_no_similarities(self) -> None:
        """Two scenes but empty similarities → single group."""
        assert find_group_boundaries([], 2) == [(0, 1)]

    def test_all_above_threshold(self) -> None:
        """All similarities above threshold → single group."""
        sims = [0.8, 0.9, 0.7]
        result = find_group_boundaries(sims, 4, threshold=0.55)
        assert result == [(0, 3)]

    def test_all_below_threshold(self) -> None:
        """All similarities below threshold → each scene is its own group.
        But min_group_size=2 merges them back."""
        sims = [0.1, 0.1, 0.1]
        result = find_group_boundaries(sims, 4, threshold=0.55, min_group_size=1)
        assert len(result) == 4
        assert result == [(0, 0), (1, 1), (2, 2), (3, 3)]

    def test_single_boundary(self) -> None:
        """Clear boundary in the middle."""
        sims = [0.9, 0.1, 0.9]  # drop at index 1
        result = find_group_boundaries(sims, 4, threshold=0.55, min_group_size=1)
        assert result == [(0, 1), (2, 3)]

    def test_multiple_boundaries(self) -> None:
        sims = [0.9, 0.1, 0.9, 0.1]  # drops at index 1, 3
        result = find_group_boundaries(sims, 5, threshold=0.55, min_group_size=1)
        assert result == [(0, 1), (2, 3), (4, 4)]

    def test_exact_threshold_no_boundary(self) -> None:
        """Similarity exactly at threshold → NOT a boundary (< threshold)."""
        sims = [0.55]
        result = find_group_boundaries(sims, 2, threshold=0.55)
        assert result == [(0, 1)]

    def test_just_below_threshold_creates_boundary(self) -> None:
        sims = [0.549]
        result = find_group_boundaries(sims, 2, threshold=0.55, min_group_size=1)
        assert result == [(0, 0), (1, 1)]

    def test_coverage_invariant(self) -> None:
        """All scenes must be covered: first group starts at 0,
        last group ends at total_scenes-1, no gaps."""
        sims = [0.9, 0.1, 0.8, 0.2, 0.7]
        result = find_group_boundaries(sims, 6, threshold=0.55, min_group_size=1)
        assert result[0][0] == 0
        assert result[-1][1] == 5
        # No gaps
        for i in range(len(result) - 1):
            assert result[i][1] + 1 == result[i + 1][0]

    def test_custom_threshold(self) -> None:
        sims = [0.3, 0.4, 0.5]
        # threshold=0.35 → only first sim is below
        result = find_group_boundaries(sims, 4, threshold=0.35, min_group_size=1)
        assert result == [(0, 0), (1, 3)]


# ======================================================================
# _merge_small_groups
# ======================================================================


class TestMergeSmallGroups:
    def test_no_small_groups(self) -> None:
        groups = [(0, 2), (3, 5)]
        sims = [0.9, 0.9, 0.1, 0.9, 0.9]
        result = _merge_small_groups(groups, sims, min_group_size=2)
        assert result == [(0, 2), (3, 5)]

    def test_single_group_stays(self) -> None:
        """A single group is never merged (no neighbors)."""
        groups = [(0, 0)]
        sims = []
        result = _merge_small_groups(groups, sims, min_group_size=2)
        assert result == [(0, 0)]

    def test_small_middle_merges_into_higher_sim_neighbor(self) -> None:
        """Small group between two large ones → merges toward higher similarity."""
        groups = [(0, 2), (3, 3), (4, 6)]  # middle group size=1
        # sim at boundary left (index 2): 0.3, right (index 3): 0.8
        sims = [0.9, 0.9, 0.3, 0.8, 0.9, 0.9]
        result = _merge_small_groups(groups, sims, min_group_size=2)
        # Middle should merge right (0.8 > 0.3)
        assert (3, 3) not in result  # small group absorbed
        # Check coverage
        assert result[0][0] == 0
        assert result[-1][1] == 6

    def test_small_at_start_merges_right(self) -> None:
        """Small group at the beginning → only right neighbor available."""
        groups = [(0, 0), (1, 3)]
        sims = [0.4, 0.9, 0.9]
        result = _merge_small_groups(groups, sims, min_group_size=2)
        assert result == [(0, 3)]

    def test_small_at_end_merges_left(self) -> None:
        """Small group at the end → only left neighbor available."""
        groups = [(0, 2), (3, 3)]
        sims = [0.9, 0.9, 0.4]
        result = _merge_small_groups(groups, sims, min_group_size=2)
        assert result == [(0, 3)]

    def test_min_group_size_3(self) -> None:
        """With min_group_size=3, groups of 2 get merged."""
        groups = [(0, 1), (2, 4)]  # first group size=2
        sims = [0.9, 0.2, 0.9, 0.9]
        result = _merge_small_groups(groups, sims, min_group_size=3)
        assert result == [(0, 4)]


# ======================================================================
# Integration: compute_pairwise_similarity → find_group_boundaries
# ======================================================================


class TestAlgorithmIntegration:
    def test_identical_scenes_one_group(self) -> None:
        """All identical embeddings → all high similarity → single group."""
        v = _uniform_vec(8)
        scenes = [_make_scene(i * 10000, text_emb=v) for i in range(5)]
        sims = compute_pairwise_similarity(scenes)
        groups = find_group_boundaries(sims, len(scenes))
        assert len(groups) == 1
        assert groups[0] == (0, 4)

    def test_two_distinct_clusters(self) -> None:
        """Two clusters of scenes with different embeddings."""
        v1 = _unit_vec(8, 0)
        v2 = _unit_vec(8, 4)
        scenes = [
            _make_scene(0, text_emb=v1),
            _make_scene(10000, text_emb=v1),
            _make_scene(20000, text_emb=v1),
            # Topic change
            _make_scene(30000, text_emb=v2),
            _make_scene(40000, text_emb=v2),
            _make_scene(50000, text_emb=v2),
        ]
        sims = compute_pairwise_similarity(scenes)
        groups = find_group_boundaries(sims, len(scenes), threshold=0.55)
        assert len(groups) == 2
        assert groups[0] == (0, 2)
        assert groups[1] == (3, 5)

    def test_gradual_transition(self) -> None:
        """Scenes that gradually shift topic — boundary depends on threshold."""
        dim = 4
        # Create scenes with gradually rotating embeddings
        scenes = []
        for i in range(6):
            v = [0.0] * dim
            # Rotate through dimensions
            v[i % dim] = 1.0
            scenes.append(_make_scene(i * 10000, text_emb=v))

        sims = compute_pairwise_similarity(scenes)
        # All orthogonal consecutive pairs → all sims = 0.0
        for s in sims:
            assert s == pytest.approx(0.0)

        groups = find_group_boundaries(sims, len(scenes), threshold=0.55, min_group_size=1)
        # Each scene is its own group when min_group_size=1
        assert len(groups) == 6

    def test_no_embeddings_single_group(self) -> None:
        """Scenes without embeddings → all neutral 0.5 → below 0.55 threshold
        → separate groups, but merged by min_group_size=2."""
        scenes = [_make_scene(i * 10000) for i in range(4)]
        sims = compute_pairwise_similarity(scenes)
        assert all(s == pytest.approx(0.5) for s in sims)
        # With threshold=0.55 these are boundaries (0.5 < 0.55)
        groups = find_group_boundaries(sims, len(scenes), threshold=0.55)
        # min_group_size=2 will cause merging
        assert groups[0][0] == 0
        assert groups[-1][1] == 3

    def test_large_video_coverage(self) -> None:
        """100 scenes — verify no gaps, all indices covered."""
        n = 100
        v = _uniform_vec(4)
        scenes = [_make_scene(i * 10000, text_emb=v) for i in range(n)]
        # Inject some boundaries
        scenes[30] = _make_scene(300000, text_emb=_unit_vec(4, 2))
        scenes[60] = _make_scene(600000, text_emb=_unit_vec(4, 3))

        sims = compute_pairwise_similarity(scenes)
        groups = find_group_boundaries(sims, n, threshold=0.55)

        # Coverage check
        assert groups[0][0] == 0
        assert groups[-1][1] == n - 1
        for i in range(len(groups) - 1):
            assert groups[i][1] + 1 == groups[i + 1][0], f"Gap at group {i}"
