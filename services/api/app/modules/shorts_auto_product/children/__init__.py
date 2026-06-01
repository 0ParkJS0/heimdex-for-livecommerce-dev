"""Wizard child runner — Phase 4 PR #4.

This sub-package is a closed boundary inside ``app.modules.shorts_auto_product``.
The child runner is the in-API-process consumer of ``mode='render_child'``
rows produced by the parent fan-out hook (``internal_router.complete``).

Loose-coupling rules (plan §15):
* The runner does NOT cross-import other ``app.modules.*`` packages.
* The runner owns catalog selection locally and uses
  ``app.dependencies.get_shorts_render_service`` as the explicit render
  boundary.
* The runner uses its own module's repos + models for DB ops.
"""

from app.modules.shorts_auto_product.children.runner import (
    ChildRunner,
    create_child_runner,
)

__all__ = ["ChildRunner", "create_child_runner"]
