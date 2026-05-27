"""Score a verdict-map JSON (output of ``replay_consolidate.py replay``)
against a golden file. Reuses the pure scoring helpers in
``app.modules.shorts_auto_product.eval.enumeration_score`` so the metric
shape matches what ``eval_shorts_auto_product.py`` reports on the live
catalog — verdict-map scoring and live-DB scoring are apples-to-apples.

"Actual labels" come from the verdict map's ``groups[].canonical_label``
list: each group represents one canonical product that would survive
into the catalog. ``rejections`` are NOT counted as actual (consolidate
soft-rejects them; they're invisible to the user). This mirrors what
``list_active_by_video`` would return after the LLM verdict landed.

Usage::

    docker compose exec -T api python -m scripts.score_verdict_map \\
        --verdict-map /tmp/replay_v22_jongga.json \\
        --golden tests/shorts_auto_product/eval/goldens/food/devorg_gd_d24cb28631262130.json \\
        [--matcher cosine] \\
        [--cosine-threshold 0.65] \\
        [--label-match-threshold 0.5] \\
        [--out /tmp/score_v22_jongga.json]

Exit codes:
    0 — both gates passed
    1 — at least one gate FAILED
    2 — runner error (file missing, malformed JSON, video_id mismatch)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from app.modules.shorts_auto_product.eval.enumeration_score import (
    DEFAULT_COSINE_THRESHOLD,
    DEFAULT_LABEL_MATCH_THRESHOLD,
    CosineLabelMatcher,
    GoldenSet,
    JaccardLabelMatcher,
    LabelMatcher,
    enumeration_precision,
    enumeration_recall,
    evaluate_gates,
)

_MATCHERS = ("jaccard", "cosine")


# Local mirror of the OpenAIEmbedder in eval_shorts_auto_product.py so
# this script stays decoupled (avoids a sibling-script import). Lazy
# import keeps the jaccard path zero-cost.
class _OpenAIEmbedder:
    DEFAULT_MODEL = "text-embedding-3-small"

    def __init__(self, *, api_key: str, model: str = DEFAULT_MODEL) -> None:
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY required for --matcher cosine. Set it in "
                "the api container env, or use --matcher jaccard."
            )
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self._client.embeddings.create(model=self._model, input=texts)
        return [list(d.embedding) for d in resp.data]


@dataclass(frozen=True)
class _ScoreReport:
    verdict_map_path: str
    golden_path: str
    video_id: str
    prompt_version: str
    matcher: str
    matcher_threshold: float
    expected_count: int
    actual_count: int
    negatives_count: int
    recall: float
    precision: float
    gates: dict
    actual_labels: list[str]  # for human eyeballing in the JSON


def _build_matcher(args: argparse.Namespace) -> tuple[LabelMatcher, float]:
    if args.matcher == "cosine":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        threshold = (
            args.cosine_threshold
            if args.cosine_threshold is not None
            else DEFAULT_COSINE_THRESHOLD
        )
        embedder = _OpenAIEmbedder(api_key=api_key)
        return CosineLabelMatcher(embedder=embedder, threshold=threshold), threshold
    return (
        JaccardLabelMatcher(threshold=args.label_match_threshold),
        args.label_match_threshold,
    )


def _prime_cosine_matcher(
    matcher: LabelMatcher,
    *,
    actual_labels: list[str],
    expected_texts: list[str],
    negatives: list[str],
) -> None:
    if not isinstance(matcher, CosineLabelMatcher):
        return
    seeds: list[str] = []
    seeds.extend(actual_labels)
    seeds.extend(expected_texts)
    seeds.extend(negatives)
    matcher.prime(seeds)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="score_verdict_map",
        description=(
            "Score a verdict-map JSON (replay_consolidate output) against "
            "a golden file using the same scoring math as "
            "eval_shorts_auto_product.py."
        ),
    )
    parser.add_argument(
        "--verdict-map", required=True,
        help="Path to verdict-map JSON (output of `replay_consolidate replay`)",
    )
    parser.add_argument(
        "--golden", required=True,
        help="Path to golden JSON (tests/shorts_auto_product/eval/goldens/...)",
    )
    parser.add_argument(
        "--matcher", default="jaccard", choices=_MATCHERS,
        help="Label-similarity matcher (default jaccard)",
    )
    parser.add_argument(
        "--label-match-threshold", type=float,
        default=DEFAULT_LABEL_MATCH_THRESHOLD,
        help=f"Jaccard threshold (default {DEFAULT_LABEL_MATCH_THRESHOLD})",
    )
    parser.add_argument(
        "--cosine-threshold", type=float, default=None,
        help=f"Cosine threshold for --matcher cosine (default {DEFAULT_COSINE_THRESHOLD})",
    )
    parser.add_argument(
        "--out", default=None,
        help="Optional JSON output path; if omitted, only prints to stdout",
    )
    args = parser.parse_args()

    vm_path = Path(args.verdict_map)
    if not vm_path.exists():
        print(f"ERROR: verdict-map not found: {vm_path}", file=sys.stderr)
        return 2
    gd_path = Path(args.golden)
    if not gd_path.exists():
        print(f"ERROR: golden not found: {gd_path}", file=sys.stderr)
        return 2

    vm = json.loads(vm_path.read_text())
    gd_raw = json.loads(gd_path.read_text())
    golden = GoldenSet.from_dict(gd_raw)

    if vm.get("video_id") != golden.video_id:
        print(
            f"ERROR: video_id mismatch — verdict-map={vm.get('video_id')!r} "
            f"vs golden={golden.video_id!r}",
            file=sys.stderr,
        )
        return 2

    actual_labels = [
        g["canonical_label"]
        for g in vm.get("groups", [])
        if g.get("canonical_label")
    ]
    expected_texts = [
        t for p in golden.expected_products for t in p.match_texts()
    ]

    matcher, threshold = _build_matcher(args)
    _prime_cosine_matcher(
        matcher,
        actual_labels=actual_labels,
        expected_texts=expected_texts,
        negatives=list(golden.expected_negatives),
    )

    recall = enumeration_recall(
        golden.expected_products, actual_labels, matcher,
    )
    precision = enumeration_precision(
        actual_labels, golden.expected_negatives, matcher,
    )
    gates = evaluate_gates(recall, precision)

    report = _ScoreReport(
        verdict_map_path=str(vm_path),
        golden_path=str(gd_path),
        video_id=golden.video_id,
        prompt_version=vm.get("prompt_version", "<unknown>"),
        matcher=args.matcher,
        matcher_threshold=threshold,
        expected_count=len(golden.expected_products),
        actual_count=len(actual_labels),
        negatives_count=len(golden.expected_negatives),
        recall=recall,
        precision=precision,
        gates=gates,
        actual_labels=actual_labels,
    )

    overall = "PASS" if gates["passed"] else "FAIL"
    print(
        f"[score] video={report.video_id} prompt={report.prompt_version} "
        f"matcher={report.matcher}@{report.matcher_threshold:.2f} | "
        f"recall={recall:.3f} ({len(actual_labels)}/{report.expected_count}) "
        f"precision={precision:.3f} | gates={overall}"
    )
    if not gates["recall"]["passed"]:
        print(
            f"  recall {recall:.3f} < {gates['recall']['floor']:.2f}",
            file=sys.stderr,
        )
    if not gates["precision"]["passed"]:
        print(
            f"  precision {precision:.3f} < {gates['precision']['floor']:.2f}",
            file=sys.stderr,
        )

    if args.out:
        Path(args.out).write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
        )

    return 0 if gates["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
