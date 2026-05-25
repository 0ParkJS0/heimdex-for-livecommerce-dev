"""Overlay-driven product catalog enumeration.

Sibling of :mod:`shorts_auto_product.enumerate_stt`. Discovers products
from operator-placed overlay graphics (product cards / price banners)
that the existing ``product-enumerate-worker`` vision path explicitly
filters out via its ``LABEL_PROMPT_SYSTEM`` (``is_product=false`` for
"on-screen graphics — chyrons, price banners, sponsor logos").

This module flips that signal: overlays are treated as operator-curated
ground-truth labels and used as the primary catalog source.

Status: **experimental, dormant**. Gated behind
``settings.auto_shorts_product_v2_overlay_track_enabled`` (default False).
Not called from any production path in this PR —
:func:`service.run_overlay_enumeration` is exposed for tests and
future wiring only.

Loose-coupling: this module imports ONLY from ``app.config``,
``opensearchpy``, ``openai``, ``boto3``, ``heimdex_media_contracts.product``,
and own-module symbols. NO cross-imports from other ``app.modules.*``.

See the module README for experiment background, workspace pointers,
and how-to-enable instructions.
"""
