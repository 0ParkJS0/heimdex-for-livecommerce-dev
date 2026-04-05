"""Tests for color extraction and histogram generation."""

from __future__ import annotations

import math

import pytest
from PIL import Image

from app.modules.search.color_extraction import (
    HISTOGRAM_DIM,
    NUM_HUE_BUCKETS,
    NUM_SAT_LEVELS,
    colors_to_hex,
    extract_dominant_colors,
    hex_to_color_histogram,
    rgb_to_hsl_histogram,
)


# --- Helpers ---


def _solid_image(r: int, g: int, b: int, size: int = 64) -> Image.Image:
    """Create a solid-color image."""
    return Image.new("RGB", (size, size), (r, g, b))


def _l2_norm(vec: list[float]) -> float:
    return math.sqrt(sum(v * v for v in vec))


def _assert_l2_normalized(vec: list[float], tol: float = 1e-6) -> None:
    norm = _l2_norm(vec)
    assert abs(norm - 1.0) < tol, f"Expected L2 norm ~1.0, got {norm}"


# --- extract_dominant_colors ---


class TestExtractDominantColors:
    def test_solid_color_returns_single_cluster(self):
        img = _solid_image(255, 0, 0)
        colors, weights = extract_dominant_colors(img, k=5)
        # All pixels are the same, so effectively 1 meaningful cluster
        assert len(colors) >= 1
        assert len(colors) == len(weights)
        # Dominant color should be close to red
        dominant = colors[0]
        assert dominant[0] > 200  # R channel high
        assert weights[0] > 0.5  # majority weight

    def test_two_color_image(self):
        img = Image.new("RGB", (128, 128))
        # Top half red, bottom half blue
        for y in range(64):
            for x in range(128):
                img.putpixel((x, y), (255, 0, 0))
        for y in range(64, 128):
            for x in range(128):
                img.putpixel((x, y), (0, 0, 255))
        colors, weights = extract_dominant_colors(img, k=2)
        assert len(colors) >= 1
        assert abs(sum(weights) - 1.0) < 0.01
        # At least the dominant color should be red or blue
        dominant_r, dominant_g, dominant_b = colors[0]
        assert dominant_r > 200 or dominant_b > 200

    def test_weights_sum_to_one(self):
        img = _solid_image(100, 150, 200)
        _, weights = extract_dominant_colors(img, k=3)
        assert abs(sum(weights) - 1.0) < 0.01

    def test_returns_rgb_tuples(self):
        img = _solid_image(128, 64, 32)
        colors, _ = extract_dominant_colors(img, k=1)
        assert len(colors) == 1
        r, g, b = colors[0]
        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255

    def test_deterministic_with_seed(self):
        img = _solid_image(100, 200, 50)
        c1, w1 = extract_dominant_colors(img, k=3, seed=42)
        c2, w2 = extract_dominant_colors(img, k=3, seed=42)
        assert c1 == c2
        assert w1 == w2

    def test_empty_image(self):
        img = Image.new("RGB", (0, 0))
        colors, weights = extract_dominant_colors(img, k=3)
        assert colors == []
        assert weights == []


# --- rgb_to_hsl_histogram ---


class TestRgbToHslHistogram:
    def test_histogram_dimension(self):
        colors = [(255, 0, 0)]
        weights = [1.0]
        hist = rgb_to_hsl_histogram(colors, weights)
        assert len(hist) == HISTOGRAM_DIM
        assert len(hist) == 27

    def test_l2_normalized(self):
        colors = [(255, 0, 0)]
        weights = [1.0]
        hist = rgb_to_hsl_histogram(colors, weights)
        _assert_l2_normalized(hist)

    def test_pure_red_in_first_hue_bucket(self):
        colors = [(255, 0, 0)]
        weights = [1.0]
        hist = rgb_to_hsl_histogram(colors, weights)
        # Red (hue=0) should land in hue bucket 0, high saturation
        chromatic_bins = hist[: NUM_HUE_BUCKETS * NUM_SAT_LEVELS]
        achromatic_bins = hist[NUM_HUE_BUCKETS * NUM_SAT_LEVELS :]
        # All weight should be in chromatic bins
        assert sum(abs(v) for v in achromatic_bins) < 0.01
        # Hue bucket 0, saturation level 2 (high sat) = index 2
        assert chromatic_bins[2] > 0.9  # dominant bin

    def test_black_goes_to_achromatic_black_bin(self):
        colors = [(0, 0, 0)]
        weights = [1.0]
        hist = rgb_to_hsl_histogram(colors, weights)
        black_bin_idx = NUM_HUE_BUCKETS * NUM_SAT_LEVELS  # index 24
        assert hist[black_bin_idx] > 0.9

    def test_white_goes_to_achromatic_white_bin(self):
        colors = [(255, 255, 255)]
        weights = [1.0]
        hist = rgb_to_hsl_histogram(colors, weights)
        white_bin_idx = NUM_HUE_BUCKETS * NUM_SAT_LEVELS + 2  # index 26
        assert hist[white_bin_idx] > 0.9

    def test_gray_goes_to_achromatic_gray_bin(self):
        colors = [(128, 128, 128)]
        weights = [1.0]
        hist = rgb_to_hsl_histogram(colors, weights)
        gray_bin_idx = NUM_HUE_BUCKETS * NUM_SAT_LEVELS + 1  # index 25
        assert hist[gray_bin_idx] > 0.9

    def test_multiple_colors_distribute_weight(self):
        colors = [(255, 0, 0), (0, 0, 255)]
        weights = [0.6, 0.4]
        hist = rgb_to_hsl_histogram(colors, weights)
        _assert_l2_normalized(hist)
        # Both chromatic, no achromatic weight
        achromatic_bins = hist[NUM_HUE_BUCKETS * NUM_SAT_LEVELS :]
        assert sum(abs(v) for v in achromatic_bins) < 0.01

    def test_empty_input_returns_zero_vector(self):
        hist = rgb_to_hsl_histogram([], [])
        assert len(hist) == HISTOGRAM_DIM
        assert all(v == 0.0 for v in hist)


# --- hex_to_color_histogram ---


class TestHexToColorHistogram:
    def test_dimension(self):
        hist = hex_to_color_histogram("#ff0000")
        assert len(hist) == HISTOGRAM_DIM

    def test_l2_normalized(self):
        hist = hex_to_color_histogram("#ff0000")
        _assert_l2_normalized(hist)

    def test_red_concentrates_in_hue_bucket_0(self):
        hist = hex_to_color_histogram("#ff0000")
        # Hue bucket 0 bins should have highest values
        bucket_0_weight = sum(hist[0:NUM_SAT_LEVELS])
        total_chromatic = sum(hist[: NUM_HUE_BUCKETS * NUM_SAT_LEVELS])
        assert bucket_0_weight / total_chromatic > 0.3

    def test_gaussian_spread_to_neighbors(self):
        hist = hex_to_color_histogram("#ff0000")
        # Neighboring hue buckets should have non-zero weight (Gaussian spread)
        bucket_1_weight = sum(hist[NUM_SAT_LEVELS : 2 * NUM_SAT_LEVELS])
        assert bucket_1_weight > 0.0

    def test_black_hex_routes_to_achromatic(self):
        hist = hex_to_color_histogram("#000000")
        black_bin = hist[NUM_HUE_BUCKETS * NUM_SAT_LEVELS]
        assert black_bin > 0.5

    def test_white_hex_routes_to_achromatic(self):
        hist = hex_to_color_histogram("#ffffff")
        white_bin = hist[NUM_HUE_BUCKETS * NUM_SAT_LEVELS + 2]
        assert white_bin > 0.5

    def test_gray_hex_routes_to_achromatic(self):
        hist = hex_to_color_histogram("#808080")
        gray_bin = hist[NUM_HUE_BUCKETS * NUM_SAT_LEVELS + 1]
        assert gray_bin > 0.5

    def test_invalid_hex_raises(self):
        with pytest.raises(ValueError):
            hex_to_color_histogram("#xyz")

    def test_similar_colors_produce_similar_histograms(self):
        h1 = hex_to_color_histogram("#ff0000")  # red
        h2 = hex_to_color_histogram("#ee1111")  # slightly different red
        h3 = hex_to_color_histogram("#0000ff")  # blue (very different)
        # Cosine similarity: red vs near-red should be higher than red vs blue
        sim_close = sum(a * b for a, b in zip(h1, h2))
        sim_far = sum(a * b for a, b in zip(h1, h3))
        assert sim_close > sim_far


# --- colors_to_hex ---


class TestColorsToHex:
    def test_basic_conversion(self):
        result = colors_to_hex([(255, 0, 0), (0, 128, 255)])
        assert result == ["#ff0000", "#0080ff"]

    def test_empty_list(self):
        assert colors_to_hex([]) == []

    def test_black_and_white(self):
        result = colors_to_hex([(0, 0, 0), (255, 255, 255)])
        assert result == ["#000000", "#ffffff"]


# --- End-to-end: image → histogram ---


class TestEndToEnd:
    def test_solid_red_image_histogram(self):
        img = _solid_image(255, 0, 0)
        colors, weights = extract_dominant_colors(img, k=3)
        hist = rgb_to_hsl_histogram(colors, weights)
        assert len(hist) == HISTOGRAM_DIM
        _assert_l2_normalized(hist)
        # Should be mostly in hue bucket 0 (red)
        chromatic_sum = sum(hist[: NUM_HUE_BUCKETS * NUM_SAT_LEVELS])
        assert chromatic_sum > 0.9

    def test_solid_black_image_histogram(self):
        img = _solid_image(0, 0, 0)
        colors, weights = extract_dominant_colors(img, k=3)
        hist = rgb_to_hsl_histogram(colors, weights)
        black_bin = hist[NUM_HUE_BUCKETS * NUM_SAT_LEVELS]
        assert black_bin > 0.9

    def test_query_matches_image(self):
        """A red query vector should be more similar to a red image than a blue image."""
        query = hex_to_color_histogram("#ff0000")

        red_img = _solid_image(255, 0, 0)
        red_colors, red_weights = extract_dominant_colors(red_img, k=3)
        red_hist = rgb_to_hsl_histogram(red_colors, red_weights)

        blue_img = _solid_image(0, 0, 255)
        blue_colors, blue_weights = extract_dominant_colors(blue_img, k=3)
        blue_hist = rgb_to_hsl_histogram(blue_colors, blue_weights)

        sim_red = sum(a * b for a, b in zip(query, red_hist))
        sim_blue = sum(a * b for a, b in zip(query, blue_hist))
        assert sim_red > sim_blue
