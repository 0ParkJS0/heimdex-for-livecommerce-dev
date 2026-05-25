"""Pure scoring helpers for the product-enumeration eval harness.

This package is INTENTIONALLY free of ``app.*`` / DB / network imports so
the scorer can be unit-tested without docker, OpenSearch, a DB, or an
embedder. The DB plumbing + CLI wiring live in
``services/api/scripts/eval_shorts_auto_product.py`` (allowed to import
``app.*`` as a one-shot script); ALL scoring math lives here.
"""

from app.modules.shorts_auto_product.eval.enumeration_score import (
    ExpectedProduct,
    GoldenSet,
    JaccardLabelMatcher,
    LabelMatcher,
    enumeration_precision,
    enumeration_recall,
    evaluate_gates,
)

__all__ = [
    "ExpectedProduct",
    "GoldenSet",
    "JaccardLabelMatcher",
    "LabelMatcher",
    "enumeration_precision",
    "enumeration_recall",
    "evaluate_gates",
]
