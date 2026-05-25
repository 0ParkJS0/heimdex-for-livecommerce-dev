"""Overlay-driven shorts assembly.

Consumes the :class:`OverlayEnumerationResult` (defined in the sibling
:mod:`shorts_auto_product.overlay_shorts.enumeration_result` module)
and produces, per product, a slot-assembled plan for a final short
clip. The shorts segment is the timeline in which the overlay was
visible -- operator-declared rather than inferred from BM25 / SAM2 /
STT. Overlay ENUMERATION itself now runs in the
``product-enumerate-worker`` (a second pass of the enumerate job); this
package consumes the persisted overlay-source catalog.

Outputs only the plan (slot list + cut boundaries). Actual ffmpeg
rendering is delegated to a downstream worker -- the existing
``shorts-render-worker`` is the natural integration point at phase 5.

Status: **experimental, dormant**. Gated behind
``settings.auto_shorts_product_v2_overlay_shorts_enabled`` (default
False). Not called from any production path in this PR --
:func:`service.run_overlay_shorts` is exposed for tests and future
wiring only.

Loose-coupling: this module imports ONLY from ``opensearchpy``,
``boto3``, :mod:`app.config`, the sibling
:mod:`shorts_auto_product.overlay_shorts.enumeration_result`, and
own-module symbols. No cross-imports from other ``app.modules.*``.
"""
