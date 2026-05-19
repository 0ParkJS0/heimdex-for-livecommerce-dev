from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # type hints only — no runtime import (local tests need no media-pipelines)
    from heimdex_media_pipelines.product_enum import CanonicalProduct


def _is_qualifier(tok: str) -> bool:
    # qualifier = number-led quantity/unit token (30, 90g, 2.5kg, 3입, 3종, 10매 …);
    # brand/product tokens never start with a digit. No Korean literals = encoding-safe.
    return tok[:1].isdigit()


def _tokens(label: str) -> set[str]:
    return {t for t in label.casefold().strip().split() if t}


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _norm_mean(vecs: list[list[float]]) -> list[float]:
    n = len(vecs)
    dim = len(vecs[0])
    acc = [0.0] * dim
    for v in vecs:
        for i, x in enumerate(v):
            acc[i] += x
    acc = [x / n for x in acc]
    norm = math.sqrt(sum(x * x for x in acc))
    return acc if norm <= 0 else [x / norm for x in acc]


def _label_match(ta: set[str], tb: set[str], jaccard: float) -> bool:
    if not ta or not tb:
        return False
    inter = ta & tb
    if not inter:
        return False
    if not any(not _is_qualifier(t) for t in inter):   # distinctive-token rule
        return False
    if ta <= tb or tb <= ta:             # containment
        return True
    return len(inter) / len(ta | tb) >= jaccard   # Jaccard


def merge_products_by_label(products, *, settings):
    """Label-gated post-merge. Identity (input unchanged) when the flag
    is off or len(products) <= 1.

    Only accepted products (rejected_reason is None) are merged; rejected
    pass through unchanged. A product joins a group iff its label matches
    AND cosine vs the group's current mean embedding >= floor.
    """
    if not getattr(settings, "enum_label_merge_enabled", False) or len(products) <= 1:
        return products

    passthrough = [p for p in products if p.rejected_reason is not None]
    cand = [p for p in products if p.rejected_reason is None]
    cand.sort(key=lambda p: (-p.cluster_size, p.canonical_scene_id,
                             p.canonical_frame_idx))
    floor = settings.enum_label_merge_cosine_floor
    jac = settings.enum_label_merge_token_jaccard

    groups: list[dict] = []
    for p in cand:
        pt = _tokens(p.llm_label)
        hit = None
        for g in groups:
            if _label_match(pt, g["tokens"], jac) and \
               _cosine(p.siglip2_embedding, g["mean_emb"]) >= floor:
                hit = g
                break
        if hit is None:
            groups.append({"members": [p],
                           "mean_emb": list(p.siglip2_embedding),
                           "tokens": pt})
        else:
            hit["members"].append(p)
            hit["mean_emb"] = _norm_mean(
                [m.siglip2_embedding for m in hit["members"]])

    merged = []
    for g in groups:
        rep = max(g["members"], key=lambda m: m.enumeration_confidence)
        merged.append(replace(
            rep,
            cluster_size=sum(m.cluster_size for m in g["members"]),
            siglip2_embedding=g["mean_emb"],
        ))
    return merged + passthrough