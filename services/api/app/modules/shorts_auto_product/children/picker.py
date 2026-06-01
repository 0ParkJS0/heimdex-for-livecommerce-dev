"""Phase 4 single-product picker — round-robin catalog selection.

The wizard's ``개별 상품`` mode produces N shorts, each dedicated to
one catalog entry. Across the N shorts, products are distributed
round-robin so 5 shorts of 3 products map to ``[c1, c2, c3, c1, c2]``
(plan §7.1).

## Why this lives in the API

Catalog IDs are API-owned database identifiers. Keeping the picker here
avoids coupling shared media packages to wizard row semantics while
still giving the child runner one deterministic owner for catalog
selection.

## Phase 5 (multi-product picker)

Phase 5 will need cross-product awareness — a single short that
mixes products. That picker DOES need ``catalog_entry_id`` visible
to the picking step, which is a more intrusive change. The plan
(§10) specifies it lives alongside this module, NOT inside the
vendored lib, for the same coupling reasons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import UUID


def pick_catalog_for_shorts_index(
    *,
    catalog_ids: Iterable[UUID],
    shorts_index: int,
) -> UUID:
    """Round-robin select one catalog id for a given ``shorts_index``.

    ``shorts_index`` is 1-based (matches the DB column convention in
    migration 052: ``CHECK (shorts_index >= 1)``).

    Determinism: ``catalog_ids`` is sorted before indexing so the
    same input set always maps to the same shorts_index → catalog.
    Without the sort, set/dict iteration order would let two API
    replicas hand the same scan order's child #2 to different
    products — which would persist to ``ProductScanJob.catalog_entry_id``
    and confuse the user-facing "which products got which short"
    rollup.

    Raises:
        ValueError: ``catalog_ids`` is empty or ``shorts_index < 1``.
    """
    ids = sorted(set(catalog_ids))
    if not ids:
        raise ValueError("catalog_ids must be non-empty")
    if shorts_index < 1:
        raise ValueError(
            f"shorts_index must be >= 1; got {shorts_index}"
        )
    # Convert 1-based index to 0-based for modulo distribution.
    return ids[(shorts_index - 1) % len(ids)]


@dataclass(frozen=True)
class CatalogPick:
    """Result of :meth:`SingleProductSubsetPicker.pick_catalog`.

    Carries the chosen ``catalog_entry_id`` and the input set's size
    so the runner can log "child 2/5 picked product 'cleanser' from
    {3 candidate products}" without redundantly recomputing.

    The runner uses ``catalog_entry_id`` to:
      * Scope STT/overlay selection to that catalog.
      * Persist on the child ``ProductScanJob`` row so the user-facing
        per-short rollup (Phase 6 wizard step 4) can show "Short 2:
        Cleanser" without an extra DB join.
    """

    catalog_entry_id: UUID
    candidates_count: int


class SingleProductSubsetPicker:
    """Phase 4 single-mode catalog selector.

    Stateless across calls — every call to :meth:`pick_catalog`
    derives its result from arguments alone. Construction takes no
    state in the Phase 4 single-mode flow; the constructor exists
    so tests + Phase 5's :class:`MultiProductSubsetPicker` can
    follow the same shape (DI for an inner picker, version stamps,
    etc.) when they ship.

    Loose-coupling: this class returns a :class:`CatalogPick` (catalog
    choice), not a window subset. After choosing a catalog, the runner
    hands the catalog to the STT/overlay selection path.
    lib-level picker (default :class:`GreedyPicker`, future LLM
    picker).
    """

    # Bumped when the catalog-selection algorithm changes in a way
    # that would alter the (shorts_index → catalog) mapping for the
    # same input. The runner persists this on the parent's
    # ``picker_version`` field so historical jobs are reproducible.
    VERSION: str = "single-rr-v1"

    def pick_catalog(
        self,
        *,
        catalog_ids: Iterable[UUID],
        shorts_index: int,
    ) -> CatalogPick:
        """Pick the catalog for ``shorts_index``.

        Thin wrapper over :func:`pick_catalog_for_shorts_index` —
        exists so the picker class can be swapped in tests and so
        the call site reads naturally:

            picker = SingleProductSubsetPicker()
            pick = picker.pick_catalog(catalog_ids=…, shorts_index=…)
        """
        # Materialize the input so we can both call the helper and
        # report the candidate count without consuming a one-shot
        # iterator twice.
        materialized = list(set(catalog_ids))
        chosen = pick_catalog_for_shorts_index(
            catalog_ids=materialized, shorts_index=shorts_index,
        )
        return CatalogPick(
            catalog_entry_id=chosen,
            candidates_count=len(materialized),
        )
