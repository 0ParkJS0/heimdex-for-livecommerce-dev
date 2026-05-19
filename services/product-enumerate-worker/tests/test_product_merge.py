from dataclasses import dataclass
import pytest
from src.product_merge import merge_products_by_label


@dataclass
class _P:  # CanonicalProduct stub (field names/types match)
    canonical_scene_id: str
    canonical_frame_idx: int
    canonical_bbox_xywh: tuple = (0, 0, 1, 1)
    canonical_crop: object = None
    llm_label: str = ""
    siglip2_embedding: list = None
    enumeration_confidence: float = 0.9
    prominence_score: float = 0.1
    cluster_size: int = 1
    rejected_reason: str | None = None


class _S:  # settings stub
    enum_label_merge_enabled = True
    enum_label_merge_token_jaccard = 0.6
    enum_label_merge_cosine_floor = 0.70
    enum_label_merge_llm_enabled = False


def _p(label, emb, conf=0.9, cs=1, rej=None, sid="s1", fi=0):
    return _P(canonical_scene_id=sid, canonical_frame_idx=fi, llm_label=label,
              siglip2_embedding=emb, enumeration_confidence=conf,
              cluster_size=cs, rejected_reason=rej)


def test_flag_off_is_identity():
    s = _S(); s.enum_label_merge_enabled = False
    ps = [_p("그린티 웨하스", [1, 0]), _p("그린티 웨하스 90g", [1, 0])]
    assert merge_products_by_label(ps, settings=s) is ps


def test_single_or_empty_unchanged():
    assert merge_products_by_label([], settings=_S()) == []
    one = [_p("a", [1, 0])]
    assert merge_products_by_label(one, settings=_S()) == one


def test_containment_high_cos_merges_and_sums_cluster_size():
    ps = [_p("그린티 웨하스", [1.0, 0.0], conf=0.8, cs=3),
          _p("그린티 웨하스 90g", [0.98, 0.02], conf=0.9, cs=2)]
    out = merge_products_by_label(ps, settings=_S())
    assert len(out) == 1
    assert out[0].cluster_size == 5
    assert out[0].llm_label == "그린티 웨하스 90g"   # representative = highest confidence


def test_cause_b_below_085_but_above_floor_merges():
    # same product, visual variance -> cos 0.80 (< 0.85 cluster thr, >= 0.70 floor)
    ps = [_p("민물장어 1kg", [1.0, 0.0]),
          _p("민물장어", [0.80, 0.60])]
    out = merge_products_by_label(ps, settings=_S())
    assert len(out) == 1


def test_diff_product_diff_tokens_not_merged():
    ps = [_p("그린티 웨하스", [1.0, 0.0]), _p("그린티 와플", [1.0, 0.0])]
    out = merge_products_by_label(ps, settings=_S())
    assert len(out) == 2


def test_qualifier_only_overlap_not_merged():
    # only shared token is a qualifier (3입) -> distinctive-token rule blocks
    # (blocked even though {3입} subset of {배,3입} via containment)
    ps = [_p("3입", [1.0, 0.0]), _p("배 3입", [1.0, 0.0])]
    out = merge_products_by_label(ps, settings=_S())
    assert len(out) == 2


def test_low_cos_blocks_label_match():
    ps = [_p("민물장어 1kg", [1.0, 0.0]), _p("민물장어 1kg", [0.0, 1.0])]
    out = merge_products_by_label(ps, settings=_S())
    assert len(out) == 2  # same label but cos 0 < floor


def test_only_accepted_merged_rejected_passthrough():
    ps = [_p("민물장어", [1, 0], cs=2),
          _p("민물장어", [1, 0], rej="single_keyframe")]
    out = merge_products_by_label(ps, settings=_S())
    labels_rej = [(p.llm_label, p.rejected_reason) for p in out]
    assert len(out) == 2
    assert ("민물장어", "single_keyframe") in labels_rej


def test_chaining_bounded_by_group_mean():
    # A=[1,0] B=[0.8,0.6](cos 0.8 to A) C=[0,1](cos 0 to A). same label.
    # A+B merge -> mean ~[0.94,0.34]; C vs mean cos ~0.34 < floor -> separate
    ps = [_p("티", [1.0, 0.0]), _p("티", [0.8, 0.6]), _p("티", [0.0, 1.0])]
    out = merge_products_by_label(ps, settings=_S())
    assert len(out) == 2