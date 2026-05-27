"""Pure, importable scorer for product-enumeration goldens.

Computes enumeration **recall** and **precision** of a video's active
``product_catalog_entries`` against a hand-curated golden, and applies
the README calibration gates. Works UNIFIED for the vision and overlay
enumeration sources — both write the same ``product_catalog_entries``
rows distinguished only by ``enumeration_source``; the scorer grades the
label set regardless of which pass produced it.

ZERO IO / DB / network / ``app.*`` imports — stdlib only. This is what
makes the harness unit-testable without docker, an embedder, OpenSearch,
or a DB. The CLI (``services/api/scripts/eval_shorts_auto_product.py``)
owns all the DB plumbing and feeds plain strings + dataclasses in here.

Label matching is pluggable via the ``LabelMatcher`` Protocol. The
default ``JaccardLabelMatcher`` is fully deterministic (NFKC-normalize →
token set → Jaccard ≥ threshold) so tests need no embedder. The README's
embedding-cosine matcher (threshold 0.65 on LLM-label embeddings) can be
injected later by the CLI without touching this module.

Gates (README ``goldens/README.md`` calibration table):
  * enumeration recall    ≥ 0.85  — failure action: swap SigLIP2 → DINOv2
  * enumeration precision  ≥ 0.80  — failure action: fall back gpt-4o-mini → gpt-4o

Window IoU is OUT OF SCOPE for this module — it grades the assembly/clip
pass, not enumeration, and overlay enumeration emits no clip windows.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Gate floors + documented failure actions (mirror goldens/README.md)
# ---------------------------------------------------------------------------

RECALL_FLOOR = 0.85
PRECISION_FLOOR = 0.80

RECALL_FAILURE_ACTION = "Swap SigLIP2 -> DINOv2 before prod"
PRECISION_FAILURE_ACTION = "Fall back to gpt-4o (from gpt-4o-mini)"

# Default token-overlap threshold for the deterministic matcher. Distinct
# from the README's embedding-cosine threshold (0.65) — token Jaccard and
# cosine sim are different scales, so they intentionally do not share a
# constant.
DEFAULT_LABEL_MATCH_THRESHOLD = 0.5

# Cosine threshold for the embedding-based matcher. Authoritative source:
# ``goldens/README.md`` §"Eval metrics computed" — "label match via cosine
# sim of LLM-label embeddings, threshold 0.65 — matches the spec
# authoring-vs-runtime label drift".
DEFAULT_COSINE_THRESHOLD = 0.65


# ---------------------------------------------------------------------------
# Golden row dataclasses (parsed from the README schema by the CLI)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpectedProduct:
    """One product the host actively presents (a golden positive).

    Mirrors the ``expected_products[]`` schema in ``goldens/README.md``.
    Only ``label_kr`` is required; the rest are optional curation hints
    that the enumeration scorer does not need but the harness preserves
    for human-readable reports + future window scoring.

    ``expected_windows_ms`` is the pre-merged half-open [start, end) ms
    ground-truth windows where the annotator marked the product as
    on-screen OR being spoken about. The enumeration scorer never reads
    this — it's the input to the SCENE-SELECTION scorer in
    :mod:`window_score`. Empty list (default) means "no ground truth
    available for window scoring" — the window scorer will mark such a
    product ungradeable.
    """

    label_kr: str
    label_en_hint: str | None = None
    first_appearance_ms: int | None = None
    expected_appearance_count_min: int | None = None
    expected_total_seconds_min: int | None = None
    category_hint: str | None = None
    expected_windows_ms: list[list[int]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> ExpectedProduct:
        return cls(
            label_kr=str(raw["label_kr"]),
            label_en_hint=raw.get("label_en_hint"),
            first_appearance_ms=raw.get("first_appearance_ms"),
            expected_appearance_count_min=raw.get("expected_appearance_count_min"),
            expected_total_seconds_min=raw.get("expected_total_seconds_min"),
            category_hint=raw.get("category_hint"),
            expected_windows_ms=[
                [int(s), int(e)]
                for s, e in raw.get("expected_windows_ms", [])
            ],
        )

    def match_texts(self) -> list[str]:
        """Label variants a candidate may match against (KR + EN hint)."""
        texts = [self.label_kr]
        if self.label_en_hint:
            texts.append(self.label_en_hint)
        return texts


@dataclass(frozen=True)
class GoldenSet:
    """A parsed golden file (one per video)."""

    video_id: str
    org_slug: str
    category: str
    enumeration_prompt_version: str
    enumeration_version: str
    tracker_version: str | None = None
    expected_products: list[ExpectedProduct] = field(default_factory=list)
    expected_negatives: list[str] = field(default_factory=list)
    schema_version: str | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> GoldenSet:
        return cls(
            video_id=str(raw["video_id"]),
            org_slug=str(raw["org_slug"]),
            category=str(raw.get("category", "")),
            enumeration_prompt_version=str(raw.get("enumeration_prompt_version", "")),
            enumeration_version=str(raw.get("enumeration_version", "")),
            tracker_version=raw.get("tracker_version"),
            expected_products=[
                ExpectedProduct.from_dict(p)
                for p in raw.get("expected_products", [])
            ],
            expected_negatives=list(raw.get("expected_negatives", [])),
            schema_version=raw.get("$schema_version"),
        )


# ---------------------------------------------------------------------------
# Label matcher Protocol + deterministic default
# ---------------------------------------------------------------------------


@runtime_checkable
class LabelMatcher(Protocol):
    """Decides whether two product labels refer to the same product.

    The default implementation is token-set Jaccard (no embedder). The
    README's embedding-cosine matcher (cosine of LLM-label embeddings,
    threshold 0.65) is a drop-in replacement the CLI can inject.
    """

    def matches(self, a: str, b: str) -> bool:  # pragma: no cover - protocol
        ...


def _normalize(text: str) -> str:
    """NFKC-normalize + casefold so width/compat variants collapse."""
    return unicodedata.normalize("NFKC", text).strip().casefold()


def _tokenize(text: str) -> frozenset[str]:
    """Whitespace token set over the normalized string.

    Korean labels are usually space-separated noun phrases ("핑크 세럼
    병"); whitespace tokenization plus NFKC handles the common
    width/compat + casing drift between authoring and runtime labels
    without an embedder.
    """
    return frozenset(t for t in _normalize(text).split() if t)


@dataclass(frozen=True)
class JaccardLabelMatcher:
    """Deterministic label matcher: token-set Jaccard ≥ threshold.

    Fully reproducible — no embedder, no network. Two variants of the
    same name (extra modifier word, different spacing, full/half-width
    digits) share enough tokens to clear the threshold; two genuinely
    different products do not.
    """

    threshold: float = DEFAULT_LABEL_MATCH_THRESHOLD

    def matches(self, a: str, b: str) -> bool:
        ta, tb = _tokenize(a), _tokenize(b)
        if not ta or not tb:
            return False
        # Exact normalized equality always matches (single-token labels
        # have Jaccard 1.0 anyway, but be explicit for clarity).
        union = ta | tb
        if not union:
            return False
        jaccard = len(ta & tb) / len(union)
        return jaccard >= self.threshold


# ---------------------------------------------------------------------------
# Embedding-cosine label matcher (Protocol + stdlib cosine + cache)
# ---------------------------------------------------------------------------


@runtime_checkable
class Embedder(Protocol):
    """Maps a batch of strings to dense embedding vectors.

    Decoupled from any specific provider so this module stays
    stdlib-only. The CLI wires an ``OpenAIEmbedder`` (text-embedding-3-
    small) at the boundary; tests pass a deterministic stub so the
    matcher contract can be pinned without a network round-trip.

    Contract: ``len(out) == len(texts)`` and every vector shares the
    same dimensionality. Order is preserved.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - protocol
        ...


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity in ``[-1, 1]``. Stdlib — no numpy.

    Returns ``0.0`` when either vector is the zero vector (degenerate;
    not a meaningful match). Raises ``ValueError`` on dim mismatch so a
    wrong-model swap surfaces loudly instead of returning silently-
    nonsense scores.
    """
    if len(a) != len(b):
        raise ValueError(
            f"embedding dim mismatch: {len(a)} vs {len(b)} — likely a "
            f"model swap mid-cache; rebuild the matcher"
        )
    dot = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(x * x for x in b))
    if da == 0.0 or db == 0.0:
        return 0.0
    return dot / (da * db)


class CosineLabelMatcher:
    """Embedding-cosine label matcher.

    Per the goldens README, two labels count as the same product when
    the cosine similarity of their embeddings is ≥ ``threshold``
    (default ``0.65`` per the spec). Designed for the auto-shorts label-
    drift case where the vision pass emits brand-stripped generic nouns
    ("포기김치 봉지") and the goldens carry full retail SKU names
    ("종가 일상행복 포기김치 10kg") — token-Jaccard 0.5 never bridges
    that pair (Jaccard ≈ 0.20); embedding cosine does.

    Embeddings are cached per ``_normalize(text)`` so width / casing
    variants collapse and the same string is never embedded twice.
    :meth:`prime` lets the caller batch-fill the cache before any
    ``matches()`` call — a single API call per video instead of N×M.
    """

    def __init__(
        self,
        embedder: Embedder,
        threshold: float = DEFAULT_COSINE_THRESHOLD,
    ) -> None:
        self._embedder = embedder
        self.threshold = threshold
        # Keyed on _normalize(text) so casing/width variants share one
        # entry. Public for diagnostics + tests — never write directly.
        self._cache: dict[str, list[float]] = {}

    @property
    def cache_size(self) -> int:
        """Number of distinct normalized labels cached (for diagnostics)."""
        return len(self._cache)

    def prime(self, texts: Iterable[str]) -> None:
        """Pre-embed every text in one batched ``embedder.embed()`` call.

        Idempotent: texts already in the cache are skipped. Empty /
        whitespace-only texts are skipped (they can never participate
        in a positive match — :meth:`matches` short-circuits on them).
        """
        wanted = sorted(
            {
                norm
                for t in texts
                if t and (norm := _normalize(t)) and norm not in self._cache
            }
        )
        if not wanted:
            return
        vecs = self._embedder.embed(wanted)
        if len(vecs) != len(wanted):
            raise RuntimeError(
                f"embedder returned {len(vecs)} vectors for {len(wanted)} "
                f"inputs — contract violation"
            )
        for text, vec in zip(wanted, vecs):
            self._cache[text] = vec

    def matches(self, a: str, b: str) -> bool:
        """True iff cosine sim of the two embeddings ≥ ``threshold``.

        Short-circuits on empty / whitespace-only inputs (False) and on
        normalized-equality (True — saves the round-trip and dodges a
        zero-vector degenerate case for self-similarity).
        """
        if not a or not b:
            return False
        na, nb = _normalize(a), _normalize(b)
        if not na or not nb:
            return False
        if na == nb:
            return True
        missing = [t for t in (na, nb) if t not in self._cache]
        if missing:
            # Lazy-fill missing pair. The CLI primes per-video to avoid
            # this hot path; tests exercise it explicitly.
            self.prime(missing)
        return _cosine_sim(self._cache[na], self._cache[nb]) >= self.threshold


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _any_match(target: str, candidates: list[str], matcher: LabelMatcher) -> bool:
    return any(matcher.matches(target, c) for c in candidates if c)


def enumeration_recall(
    expected_products: list[ExpectedProduct],
    actual_labels: list[str],
    matcher: LabelMatcher,
) -> float:
    """Fraction of ``expected_products`` matched by ≥1 actual label.

    An expected product counts as surfaced if ANY of its label variants
    (``label_kr`` and the optional ``label_en_hint``) matches ANY actual
    catalog label under ``matcher``. Empty expected set → 1.0 (a video
    with no expected products is trivially fully recalled).
    """
    if not expected_products:
        return 1.0
    matched = 0
    for exp in expected_products:
        if any(
            _any_match(variant, actual_labels, matcher)
            for variant in exp.match_texts()
        ):
            matched += 1
    return matched / len(expected_products)


def enumeration_precision(
    actual_labels: list[str],
    expected_negatives: list[str],
    matcher: LabelMatcher,
) -> float:
    """1 − fraction of actual labels matching any ``expected_negative``.

    Grades pollution: catalog rows that match a curated negative (host
    accessory, sponsor prop, background object) are false positives. No
    actual labels → 1.0 (nothing to be wrong about). No negatives → 1.0
    (no curated pollution list to penalize against; the README treats
    ``expected_negatives`` as optional).
    """
    if not actual_labels:
        return 1.0
    if not expected_negatives:
        return 1.0
    polluted = sum(
        1
        for label in actual_labels
        if _any_match(label, expected_negatives, matcher)
    )
    return 1.0 - (polluted / len(actual_labels))


def evaluate_gates(recall: float, precision: float) -> dict:
    """Apply the README calibration floors; return a pass/fail report.

    Returns a dict with overall ``passed`` plus per-metric blocks
    carrying the value, floor, pass flag, and the documented failure
    action string (so the CLI can print the exact remediation, not a
    generic "below threshold").
    """
    recall_passed = recall >= RECALL_FLOOR
    precision_passed = precision >= PRECISION_FLOOR
    return {
        "passed": recall_passed and precision_passed,
        "recall": {
            "value": recall,
            "floor": RECALL_FLOOR,
            "passed": recall_passed,
            "failure_action": None if recall_passed else RECALL_FAILURE_ACTION,
        },
        "precision": {
            "value": precision,
            "floor": PRECISION_FLOOR,
            "passed": precision_passed,
            "failure_action": (
                None if precision_passed else PRECISION_FAILURE_ACTION
            ),
        },
    }
